"""
将本地历史数据导入到 SQLite 数据库（适用于 fly.io Volume 上的 fuel.db）。

功能：
  1. 仅导入最近 90 天以内的历史记录
  2. 边界向前填充：若某 station 在第 90 天当天没有记录，
     则向前追溯，找到该 station 在第 90 天之前最近一条有效记录，
     将其价格以边界日期（第 90 天 00:00:00 UTC）插入，
     保证数据连续性。
  3. 使用 INSERT OR IGNORE 防止重复插入（通过唯一索引）。
  4. 同时确保所有涉及的 station 都已写入 stations 表。

用法（本地生成导入用的 DB，再上传到 fly.io）：
    python scripts/import_history.py [选项]

选项：
    --db          目标数据库路径（默认：data/fuel.db）
    --history-dir 历史数据目录（默认：data/history）
    --stations    站点信息 JSON（默认：data/stations_all.json）
    --days        导入天数窗口（默认：90）
    --dry-run     仅统计，不写入数据库
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 日志配置 ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# 历史 JSON 中除 "currency"、"date_added" 之外的键均视为燃油类型
_NON_FUEL_KEYS = {"currency", "date_added"}


def _parse_utc(ts: str) -> datetime:
    """将 ISO 8601 字符串解析为 UTC datetime（兼容末尾 Z 或 +00:00）。"""
    ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def _init_schema(conn: sqlite3.Connection) -> None:
    """确保数据库 schema 已创建。"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stations (
            station_id  TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            brand       TEXT,
            address     TEXT,
            town        TEXT,
            county      TEXT,
            latitude    REAL NOT NULL,
            longitude   REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id  TEXT NOT NULL REFERENCES stations(station_id),
            fuel_type   TEXT NOT NULL,
            price       REAL NOT NULL,
            observed_at TEXT NOT NULL
        )
    """)
    # 唯一索引：同一 station + 燃油类型 + 时间戳只允许一条记录，防止重复插入
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_price_history_station_fuel_time
            ON price_history(station_id, fuel_type, observed_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_price_history_station_fuel
            ON price_history(station_id, fuel_type, observed_at)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id  TEXT NOT NULL,
            price       REAL NOT NULL,
            score       REAL NOT NULL,
            sent_at     TEXT NOT NULL
        )
    """)


def _upsert_station(conn: sqlite3.Connection, station: dict) -> None:
    """将站点信息写入 stations 表（不存在则插入，已存在则跳过）。"""
    conn.execute("""
        INSERT OR IGNORE INTO stations
            (station_id, name, brand, address, town, county, latitude, longitude)
        VALUES
            (:station_id, :name, :brand, :address, :town, :county, :latitude, :longitude)
    """, {
        "station_id": station["station_id"],
        "name":       station.get("name", ""),
        "brand":      station.get("brand"),
        "address":    station.get("address"),
        "town":       station.get("town"),
        "county":     station.get("county"),
        "latitude":   station.get("latitude", 0.0),
        "longitude":  station.get("longitude", 0.0),
    })


def load_stations(stations_path: Path) -> dict[str, dict]:
    """读取 stations_all.json，返回 {station_id: station_dict} 映射。"""
    stations_list: list[dict] = json.loads(stations_path.read_text(encoding="utf-8"))
    return {s["station_id"]: s for s in stations_list}


def import_history(
    db_path: Path,
    history_dir: Path,
    stations_map: dict[str, dict],
    days: int = 90,
    dry_run: bool = False,
) -> None:
    """
    主导入逻辑。

    参数：
        db_path      目标 SQLite 数据库路径
        history_dir  本地历史数据目录（每个文件为 <station_id>.json）
        stations_map {station_id: station_dict} 映射
        days         时间窗口（天数，默认 90）
        dry_run      若为 True，仅统计不写库
    """
    now = datetime.now(timezone.utc)
    # 时间窗口起始点：精确到当天 00:00:00 UTC，以便边界填充逻辑对齐到整天
    boundary_dt = (now - timedelta(days=days)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    logger.info("时间窗口：%s → %s（最近 %d 天）",
                boundary_dt.isoformat(), now.isoformat(), days)

    history_files = sorted(history_dir.glob("*.json"))
    total_files = len(history_files)
    logger.info("共发现 %d 个历史数据文件", total_files)

    # 统计计数器
    cnt_stations_upserted = 0
    cnt_inserted = 0
    cnt_skipped_no_data = 0
    cnt_boundary_filled = 0
    cnt_ignored_duplicate = 0

    conn: sqlite3.Connection | None = None
    if not dry_run:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _init_schema(conn)
        logger.info("数据库已连接：%s", db_path)

    for idx, history_file in enumerate(history_files, start=1):
        station_id = history_file.stem

        # 读取历史记录
        try:
            records: list[dict] = json.loads(history_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[%d/%d] %s 解析失败：%s，跳过", idx, total_files, station_id, exc)
            continue

        if not records:
            cnt_skipped_no_data += 1
            continue

        # 确保站点存在于 stations 表
        station_meta = stations_map.get(station_id)
        if station_meta is None:
            # 若 stations_all.json 中没有该站点，构造最小信息
            station_meta = {
                "station_id": station_id,
                "name": station_id,
                "brand": None,
                "address": None,
                "town": None,
                "county": None,
                "latitude": 0.0,
                "longitude": 0.0,
            }

        if not dry_run:
            _upsert_station(conn, station_meta)
            cnt_stations_upserted += 1

        # 解析所有记录并提取燃油类型
        # 历史 JSON 格式示例：
        #   {"petrol": 173.9, "currency": "euro", "date_added": "2025-10-12T17:28:26Z"}
        parsed: list[tuple[datetime, str, float]] = []  # (observed_at, fuel_type, price)

        for rec in records:
            try:
                observed_at = _parse_utc(rec["date_added"])
            except (KeyError, ValueError):
                continue

            for key, val in rec.items():
                if key in _NON_FUEL_KEYS:
                    continue
                if not isinstance(val, (int, float)):
                    continue
                # 历史 JSON 中价格为分（cents）单位，转换为欧元（与 collector.py 一致）
                # 过滤无效值：0 以下或超过 500 分（€5/L）视为脏数据
                if val <= 0 or val > 500:
                    continue
                price_eur = float(val)
                parsed.append((observed_at, key, price_eur))

        if not parsed:
            cnt_skipped_no_data += 1
            continue

        # 按燃油类型分组，分别处理
        # 将 parsed 按燃油类型分组
        fuel_records: dict[str, list[tuple[datetime, float]]] = {}
        for observed_at, fuel_type, price in parsed:
            fuel_records.setdefault(fuel_type, []).append((observed_at, price))

        for fuel_type, ts_prices in fuel_records.items():
            # 按时间升序排列
            ts_prices.sort(key=lambda x: x[0])

            # ── 边界向前填充逻辑 ─────────────────────────────────────────────
            # 找到窗口内最早的记录
            in_window = [(dt, p) for dt, p in ts_prices if dt >= boundary_dt]

            # 如果窗口内第一条记录不是刚好在 boundary_dt，
            # 则向前追溯（即窗口起始边界当天没有数据）
            if not in_window or in_window[0][0] > boundary_dt:
                # 找到 boundary_dt 之前最近的一条记录
                before_window = [(dt, p) for dt, p in ts_prices if dt < boundary_dt]
                if before_window:
                    # 取最近的一条（列表已升序，取最后一条）
                    _, fill_price = before_window[-1]
                    # 将该价格以 boundary_dt 的时间戳填充
                    fill_ts = boundary_dt.isoformat()
                    if not dry_run:
                        try:
                            conn.execute("""
                                INSERT OR IGNORE INTO price_history
                                    (station_id, fuel_type, price, observed_at)
                                VALUES (?, ?, ?, ?)
                            """, (station_id, fuel_type, fill_price, fill_ts))
                            if conn.execute("SELECT changes()").fetchone()[0] > 0:
                                cnt_boundary_filled += 1
                                cnt_inserted += 1
                            else:
                                cnt_ignored_duplicate += 1
                        except sqlite3.Error as exc:
                            logger.error("填充边界记录失败 %s/%s：%s", station_id, fuel_type, exc)
                    else:
                        cnt_boundary_filled += 1
                        cnt_inserted += 1

            # ── 插入窗口内的正常记录 ─────────────────────────────────────────
            for observed_at, price in in_window:
                ts_str = observed_at.isoformat()
                if not dry_run:
                    try:
                        conn.execute("""
                            INSERT OR IGNORE INTO price_history
                                (station_id, fuel_type, price, observed_at)
                            VALUES (?, ?, ?, ?)
                        """, (station_id, fuel_type, price, ts_str))
                        if conn.execute("SELECT changes()").fetchone()[0] > 0:
                            cnt_inserted += 1
                        else:
                            cnt_ignored_duplicate += 1
                    except sqlite3.Error as exc:
                        logger.error("插入记录失败 %s/%s：%s", station_id, fuel_type, exc)
                else:
                    cnt_inserted += 1

        # 每处理 100 个站点提交一次事务，减少内存压力
        if not dry_run and idx % 100 == 0:
            conn.commit()
            logger.info("  进度：%d/%d 站点已处理，已插入 %d 条", idx, total_files, cnt_inserted)

    # 最终提交
    if not dry_run and conn:
        conn.commit()
        conn.close()
        logger.info("数据库连接已关闭")

    # 输出汇总
    logger.info("=" * 60)
    logger.info("导入完成！汇总：")
    logger.info("  处理历史文件：%d 个", total_files)
    logger.info("  跳过（无数据）：%d 个站点", cnt_skipped_no_data)
    logger.info("  新插入记录数：%d 条", cnt_inserted)
    logger.info("    其中边界填充：%d 条", cnt_boundary_filled)
    logger.info("  忽略重复记录：%d 条", cnt_ignored_duplicate)
    if dry_run:
        logger.info("  [DRY RUN 模式，未实际写入数据库]")
    logger.info("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="将本地历史数据导入 fuel.db（支持 90 天过滤与边界向前填充）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db",
        default="data/fuel.db",
        help="目标 SQLite 数据库路径（默认：data/fuel.db）",
    )
    parser.add_argument(
        "--history-dir",
        default="data/history",
        help="历史数据目录（默认：data/history）",
    )
    parser.add_argument(
        "--stations",
        default="data/stations_all.json",
        help="站点信息 JSON 文件（默认：data/stations_all.json）",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="导入时间窗口天数（默认：90）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅统计，不实际写入数据库",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    history_dir = Path(args.history_dir)
    stations_path = Path(args.stations)

    if not history_dir.exists():
        logger.error("历史数据目录不存在：%s", history_dir)
        sys.exit(1)

    if not stations_path.exists():
        logger.warning("站点信息文件不存在：%s，将使用最小化站点元数据", stations_path)
        stations_map: dict[str, dict] = {}
    else:
        stations_map = load_stations(stations_path)
        logger.info("已加载 %d 个站点元数据", len(stations_map))

    import_history(
        db_path=db_path,
        history_dir=history_dir,
        stations_map=stations_map,
        days=args.days,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
