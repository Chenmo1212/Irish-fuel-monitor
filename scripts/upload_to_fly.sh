#!/usr/bin/env bash
# =============================================================================
# upload_to_fly.sh
# 将本地历史数据导入数据库后上传到 fly.io Volume
# =============================================================================

set -euo pipefail

# 配置
APP_NAME="fuel-monitor-bot"
DAYS=90
LOCAL_DB="data/fuel_import.db"
REMOTE_DB="/app/data/fuel.db"

# 颜色输出
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
RESET="\033[0m"
BOLD="\033[1m"

info()  { echo -e "${GREEN}[INFO]${RESET}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; }

echo -e "${BOLD}============================================================${RESET}"
echo -e "${BOLD} Fuel Monitor - 历史数据上传到 fly.io${RESET}"
echo -e "${BOLD}============================================================${RESET}"
echo

# 步骤 1：检查依赖
info "步骤 1/5：检查依赖..."

if ! command -v flyctl &>/dev/null && ! command -v fly &>/dev/null; then
    error "未找到 flyctl。请先安装：https://fly.io/docs/hands-on/install-flyctl/"
    exit 1
fi
FLY_CMD=$(command -v flyctl 2>/dev/null || command -v fly)
info "  flyctl 路径：${FLY_CMD}"

if ! command -v python3 &>/dev/null; then
    error "未找到 python3"
    exit 1
fi

# 步骤 2：生成本地导入数据库
info "步骤 2/5：生成本地导入数据库（最近 ${DAYS} 天）..."

rm -f "${LOCAL_DB}"

if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
    info "  已激活虚拟环境 .venv"
fi

python3 scripts/import_history.py \
    --db "${LOCAL_DB}" \
    --history-dir data/history \
    --stations data/stations_all.json \
    --days "${DAYS}"

if [ ! -f "${LOCAL_DB}" ]; then
    error "数据库生成失败，文件不存在：${LOCAL_DB}"
    exit 1
fi

DB_SIZE=$(du -sh "${LOCAL_DB}" | cut -f1)
info "  本地数据库已生成：${LOCAL_DB} (大小：${DB_SIZE})"

# 步骤 3：确保应用有一台 VM 在运行（sftp 需要）
info "步骤 3/5：确保应用有 VM 运行以支持文件传输..."
"${FLY_CMD}" scale count 1 --app "${APP_NAME}" --yes 2>&1 || true
info "  等待 VM 启动..."
sleep 8

# 步骤 4：通过 fly sftp 上传数据库
info "步骤 4/5：通过 fly sftp 上传数据库到 ${REMOTE_DB}..."

# VACUUM INTO 生成无 WAL 的干净单文件数据库（直接传输 WAL 模式数据库会损坏）
UPLOAD_DB="${LOCAL_DB%.db}_upload.db"
python3 -c "
import sqlite3, os, sys
src, dst = sys.argv[1], sys.argv[2]
for f in [dst, dst+'-wal', dst+'-shm']:
    if os.path.exists(f): os.remove(f)
sqlite3.connect(src).execute(f'VACUUM INTO \"{dst}\"')
count = sqlite3.connect(dst).execute('SELECT COUNT(*) FROM price_history').fetchone()[0]
print(f'  VACUUM 完成，{count} 条记录，{os.path.getsize(dst)//1024} KB')
" "${LOCAL_DB}" "${UPLOAD_DB}"

# 删除远端旧文件（fly sftp 不允许覆盖，必须先删）
info "  备份并删除远端旧数据库..."
"${FLY_CMD}" ssh console --app "${APP_NAME}" --command "cp ${REMOTE_DB} ${REMOTE_DB}.bak 2>/dev/null; rm -f ${REMOTE_DB}" 2>/dev/null || true

# 上传新文件
"${FLY_CMD}" sftp shell --app "${APP_NAME}" <<EOF
put ${UPLOAD_DB} ${REMOTE_DB}
EOF

rm -f "${UPLOAD_DB}"
info "  数据库上传完成（旧文件已备份为 ${REMOTE_DB}.bak）"

# 步骤 5：重启应用让新数据库生效
info "步骤 5/5：重启 fly.io 应用..."
MACHINE_ID=$("${FLY_CMD}" machine list --app "${APP_NAME}" --json \
    | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])" 2>/dev/null || true)
if [ -n "${MACHINE_ID}" ]; then
    "${FLY_CMD}" machine restart "${MACHINE_ID}" --app "${APP_NAME}"
else
    warn "  无法获取 machine ID，请手动执行：fly machine restart --app ${APP_NAME}"
fi
"${FLY_CMD}" status --app "${APP_NAME}"

# 清理临时文件
rm -f "${LOCAL_DB}"
info "  临时数据库已清理：${LOCAL_DB}"

echo
echo -e "${BOLD}============================================================${RESET}"
echo -e "${GREEN}${BOLD} 所有步骤完成！历史数据已成功上传到 fly.io${RESET}"
echo -e "${BOLD}============================================================${RESET}"
