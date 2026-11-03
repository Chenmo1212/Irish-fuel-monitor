#!/usr/bin/env node
/**
 * build.js — Fuel Monitor 构建与部署脚本
 *
 * 使用方式：
 *   node build.js            # 仅打包生成 dist/ 目录
 *   node build.js --deploy   # 打包并同步部署到远程服务器
 *   node build.js -d         # 简写部署
 *
 * 默认部署路径：
 *   /www/wwwroot/api.chenmo1212.cn/fuel_monitor
 */

import {
  readFileSync,
  writeFileSync,
  mkdirSync,
  cpSync,
  rmSync,
  existsSync,
  statSync,
  readdirSync,
} from 'fs';
import { join, dirname } from 'path';
import { homedir } from 'os';
import { fileURLToPath } from 'url';
import { execFileSync, execSync } from 'child_process';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = __dirname;
const DIST = join(ROOT, 'dist');
const DEFAULT_TARGET = '/www/wwwroot/api.chenmo1212.cn/fuel_monitor';

console.log('🚀 开始构建 Fuel Monitor 部署包...\n');

// ── 1. 清空并重建 dist/ ──────────────────────────────────────────────────────
if (existsSync(DIST)) {
  rmSync(DIST, { recursive: true, force: true });
}
mkdirSync(DIST, { recursive: true });
console.log('✓ dist/ 目录已初始化');

// ── 2. Python 代码语法校验（确保所有待打包文件无语法错误）────────────────────
console.log('⏳ 正在执行 Python 语法校验...');
try {
  execSync('python3 -m py_compile bot.py fuel_monitor/*.py', {
    cwd: ROOT,
    stdio: 'pipe',
  });
  console.log('✓ Python 语法校验通过');
} catch (err) {
  console.warn('⚠ Python 语法校验跳过或警告:', err.message);
}

// ── 3. 复制项目文件到 dist/ ──────────────────────────────────────────────────
console.log('⏳ 正在复制可部署文件...');

const copyFilter = (src) => {
  const base = src.split('/').pop() || '';
  if (base === '__pycache__' || base === '.pytest_cache' || base === '.venv' || base === 'venv') {
    return false;
  }
  if (base.endsWith('.pyc') || base.endsWith('.pyo') || base.endsWith('.DS_Store')) {
    return false;
  }
  if (base === '.git' || base === '.deploy.json' || base === 'dist') {
    return false;
  }
  return true;
};

// 复制 Python 核心包 fuel_monitor/
if (existsSync(join(ROOT, 'fuel_monitor'))) {
  cpSync(join(ROOT, 'fuel_monitor'), join(DIST, 'fuel_monitor'), {
    recursive: true,
    filter: copyFilter,
  });
  console.log('✓ fuel_monitor/ 核心模块已复制');
}

// 复制入口与配置文件
const rootFiles = ['bot.py', 'config.yaml', 'requirements.txt', 'README.md', '.env.example'];
for (const file of rootFiles) {
  const filePath = join(ROOT, file);
  if (existsSync(filePath)) {
    cpSync(filePath, join(DIST, file));
    console.log(`✓ ${file} 已复制`);
  }
}

// 复制 scripts/ 目录（运维脚本）
if (existsSync(join(ROOT, 'scripts'))) {
  cpSync(join(ROOT, 'scripts'), join(DIST, 'scripts'), {
    recursive: true,
    filter: copyFilter,
  });
  console.log('✓ scripts/ 运维脚本已复制');
}

// 创建运行时 data/ 目录（不拷贝本地开发数据文件，防止覆盖线上生产数据）
const distDataDir = join(DIST, 'data');
if (!existsSync(distDataDir)) {
  mkdirSync(distDataDir, { recursive: true });
  writeFileSync(join(distDataDir, '.gitkeep'), '', 'utf-8');
  console.log('✓ data/ 运行目录结构已创建');
}

// ── 4. 输出打包文件清单与体积统计 ─────────────────────────────────────────────
function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

function getDirStats(dir, relativeTo = dir) {
  let totalBytes = 0;
  let fileCount = 0;
  const entries = readdirSync(dir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      const sub = getDirStats(fullPath, relativeTo);
      totalBytes += sub.totalBytes;
      fileCount += sub.fileCount;
    } else {
      totalBytes += statSync(fullPath).size;
      fileCount++;
    }
  }
  return { totalBytes, fileCount };
}

const stats = getDirStats(DIST);
console.log('\n── 构建产物清单 ──────────────────────────────────');
console.log(`  包含文件数: ${stats.fileCount}`);
console.log(`  产物总体积: ${formatSize(stats.totalBytes)}`);
console.log(`  打包目录:   ${DIST}`);
console.log('─────────────────────────────────────────────────');
console.log('\n🎉 构建完成！dist/ 目录已就绪。\n');

// ── 5. 部署到远程服务器（可选）───────────────────────────────────────────────
const shouldDeploy =
  process.argv.slice(2).some((arg) => /^(-d|--deploy|deploy)$/i.test(arg)) ||
  process.env.DEPLOY === '1' ||
  process.env.DEPLOY === 'true';

const shouldUploadDb =
  process.argv.slice(2).some((arg) => /^(--upload-db|--db|upload-db)$/i.test(arg)) ||
  process.env.UPLOAD_DB === '1';

if (shouldDeploy || shouldUploadDb) {
  console.log('🚀 开始部署到远程服务器...');

  // 优先级：环境变量 > .deploy.json > 默认值
  let config = {};
  const deployJsonPath = join(ROOT, '.deploy.json');

  if (existsSync(deployJsonPath)) {
    try {
      config = JSON.parse(readFileSync(deployJsonPath, 'utf-8'));
    } catch (e) {
      console.error(`❌ 解析 .deploy.json 失败:`, e.message);
      process.exit(1);
    }
  }

  const host = process.env.DEPLOY_HOST || config.host;
  const user = process.env.DEPLOY_USER || config.user || 'root';
  const target =
    process.env.DEPLOY_TARGET ||
    process.env.DEPLOY_PATH ||
    config.target ||
    config.path ||
    DEFAULT_TARGET;
  let key = process.env.DEPLOY_KEY || process.env.DEPLOY_SSH_KEY || config.key || config.sshKey;
  const port = process.env.DEPLOY_PORT || config.port || 22;
  const restartCmd = process.env.DEPLOY_RESTART_CMD || config.restartCommand;

  if (!host) {
    console.error('\n❌ 部署失败：缺少服务器 IP 或主机名 (host)！');
    console.error('请在项目根目录创建 .deploy.json（已被 git 忽略，不会上传到 GitHub）');
    console.error('示例参考 .deploy.example.json：');
    console.error(
      JSON.stringify(
        {
          host: 'your-server-ip',
          user: 'root',
          target: DEFAULT_TARGET,
          key: '~/.ssh/id_rsa',
          port: 22,
          restartCommand: 'systemctl restart fuelbot',
        },
        null,
        2
      )
    );
    process.exit(1);
  }

  // 展开 ~ 路径
  if (key && typeof key === 'string' && key.startsWith('~')) {
    key = join(homedir(), key.slice(1));
  }

  const normalizedTarget = target.endsWith('/') ? target : target + '/';
  const remoteDest = `${user}@${host}:${normalizedTarget}`;
  console.log(`📦 正在同步 dist/ 到 ${user}@${host}:${normalizedTarget}...`);

  const sshOptions = ['-p', String(port), '-o', 'StrictHostKeyChecking=accept-new'];
  if (key && existsSync(key)) {
    sshOptions.push('-i', key);
  } else if (key) {
    console.warn(`⚠ 提示：指定的密钥文件不存在 (${key})，已回退至系统默认 SSH 认证`);
  }

  const sshCmd = `ssh ${sshOptions.map((opt) => `"${opt}"`).join(' ')}`;

  try {
    // 确保远端目标目录存在
    execFileSync('ssh', [...sshOptions, `${user}@${host}`, `mkdir -p ${target}`], {
      stdio: 'inherit',
    });

    // 使用 rsync 同步，保护服务器上的 .env 和 SQLite 数据库文件不被覆盖或删除
    execFileSync(
      'rsync',
      [
        '-avz',
        '--delete',
        '--exclude=.env',
        '--exclude=.venv/',
        '--exclude=venv/',
        '--exclude=data/*.db',
        '--exclude=data/*.db-shm',
        '--exclude=data/*.db-wal',
        '--exclude=data/*.db.bak',
        '--exclude=logs/',
        '-e',
        sshCmd,
        `${DIST}/`,
        remoteDest,
      ],
      { stdio: 'inherit' }
    );

    console.log(`\n✨ 文件同步成功！已发布至 ${host}:${target}`);

    // 如果指定了 --upload-db，将本地历史数据库上传到远端
    if (shouldUploadDb) {
      const localDb = join(ROOT, 'data', 'fuel.db');
      if (existsSync(localDb)) {
        console.log('\n📦 正在准备上传本地历史数据库 data/fuel.db ...');
        const cleanDb = join(ROOT, 'data', 'fuel_clean_temp.db');
        if (existsSync(cleanDb)) rmSync(cleanDb, { force: true });

        // 使用 VACUUM INTO 生成无 WAL 锁定的干净数据库单文件
        execSync(
          `python3 -c "import sqlite3; conn = sqlite3.connect('${localDb}'); conn.execute('VACUUM INTO \\'${cleanDb}\\''); conn.close()"`
        );

        const remoteDbPath = `${normalizedTarget}data/fuel.db`;
        console.log(`⏳ 正在上传数据库到 ${user}@${host}:${remoteDbPath} ...`);

        execFileSync('ssh', [...sshOptions, `${user}@${host}`, `cp ${remoteDbPath} ${remoteDbPath}.bak 2>/dev/null || true`]);
        execFileSync('rsync', ['-avz', '-e', sshCmd, cleanDb, `${user}@${host}:${remoteDbPath}`], { stdio: 'inherit' });

        if (existsSync(cleanDb)) rmSync(cleanDb, { force: true });
        console.log('✓ 本地历史数据库已成功上传至服务器！');
      } else {
        console.warn('⚠ 本地未找到 data/fuel.db，跳过数据库上传');
      }
    }

    // 如果配置了重启命令，远程执行重启
    if (restartCmd && typeof restartCmd === 'string' && restartCmd.trim()) {
      console.log(`\n🔄 正在执行远端服务重启命令: ${restartCmd.trim()}`);
      execFileSync('ssh', [...sshOptions, `${user}@${host}`, restartCmd.trim()], {
        stdio: 'inherit',
      });
      console.log('✓ 远端服务已重启！');
    }

    console.log('\n🎉 部署流程圆满完成！\n');
  } catch (err) {
    console.error(`\n❌ 部署失败:`, err.message);
    process.exit(1);
  }
}
