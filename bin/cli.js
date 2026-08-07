#!/usr/bin/env node
'use strict';

/*
 * free-short-video — npm launcher
 *
 * Installs/runs the full Agnes Video Generator (Python/FastAPI) service on the
 * user's machine with zero manual setup beyond a Python 3.10+ interpreter:
 *   1. detect python3 >= 3.10
 *   2. create a venv inside the package
 *   3. pip install -r requirements.txt  (pulls moviepy + imageio-ffmpeg)
 *   4. expose imageio-ffmpeg's static ffmpeg binary on PATH (no system ffmpeg needed)
 *   5. spawn `python server.py` with PORT/HOST + optional AGNES_API_KEY
 *   6. auto-open the browser, forward Ctrl+C for graceful shutdown
 */

const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const PKG_ROOT = path.resolve(__dirname, '..');

// 终端超链接（ANSI OSC 8）：TTY 下输出可点击链接，非 TTY（管道/重定向）降级为纯文本
const link = (url, text) =>
  process.stdout.isTTY ? `\x1b]8;;${url}\x1b\\${text}\x1b]8;;\x1b\\` : text;

// 启动图案（ASCII art）：TTY 下亮青色显示，非 TTY 纯文本
const FSV_LOGO = String.raw`   _____ ______     __
  |  ___/ ___\ \   / /
  | |_  \___ \\ \ / /
  |  _|  ___) |\ V /
  |_|   |____/  \_/`.split('\n');
function printLogo() {
  if (process.stdout.isTTY) {
    console.log('\x1b[1;36m');
    FSV_LOGO.forEach((l) => console.log(l));
    process.stdout.write('\x1b[0m');
  } else {
    console.log('');
    FSV_LOGO.forEach((l) => console.log(l));
  }
}

function printHelp() {
  console.log(`free-short-video — free AI short-video generator

Usage:
  npx free-short-video [options]
  fsv [options]

Options:
  --port <n>     Listen port (default 8765)
  --host <h>     Bind host (default 127.0.0.1; use 0.0.0.0 for LAN)
  --no-open      Do not auto-open the browser
  -h, --help     Show this help

Environment:
  AGNES_API_KEY  Your Agnes API key (can also be set later in the Web UI)

Website:
  ${link('https://video.lichuanyang.top', 'https://video.lichuanyang.top')}   (official site & no-install online demo)

First run creates a local venv and installs Python dependencies automatically.
`);
}

// ── parse args ────────────────────────────────────────────────────────────
let port = 8765;
let host = '127.0.0.1';
let openBrowser = true;

const argv = process.argv.slice(2);
for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === '--port') {
    const v = parseInt(argv[++i], 10);
    if (!Number.isNaN(v)) port = v;
  } else if (a === '--host') {
    host = argv[++i] || host;
  } else if (a === '--no-open') {
    openBrowser = false;
  } else if (a === '-h' || a === '--help') {
    printHelp();
    process.exit(0);
  } else {
    console.error(`Unknown option: ${a}\n`);
    printHelp();
    process.exit(1);
  }
}

// ── helpers ───────────────────────────────────────────────────────────────
function run(cmd, opts) {
  return execSync(cmd, Object.assign({ stdio: 'inherit', cwd: PKG_ROOT }, opts));
}

function findPython() {
  for (const cmd of ['python3', 'python']) {
    try {
      const out = execSync(`"${cmd}" --version`, { stdio: ['ignore', 'pipe', 'ignore'] })
        .toString()
        .trim();
      const m = out.match(/Python (\d+)\.(\d+)/);
      if (m && (parseInt(m[1], 10) > 3 || (parseInt(m[1], 10) === 3 && parseInt(m[2], 10) >= 10))) {
        return cmd;
      }
    } catch (_) {
      /* not found / wrong version */
    }
  }
  return null;
}

function venvBin(name) {
  return process.platform === 'win32'
    ? path.join(PKG_ROOT, '.venv', 'Scripts', `${name}.exe`)
    : path.join(PKG_ROOT, '.venv', 'bin', name);
}

// ── 1. python check ───────────────────────────────────────────────────────
console.log('================================================');
printLogo();
console.log('   free-short-video — Free AI short-video generator');
console.log('');
console.log(`   🌐 官网: ${link('https://video.lichuanyang.top', 'https://video.lichuanyang.top')}  |  ⚡ 在线体验: ${link('https://video.lichuanyang.top/demo', 'https://video.lichuanyang.top/demo')}`);
console.log('================================================');
console.log('');

const py = findPython();
if (!py) {
  console.error('❌ Python 3.10+ is required but was not found.');
  console.error('   macOS:   brew install python3');
  console.error('   Ubuntu:  sudo apt install python3 python3-venv');
  console.error('   Windows: https://www.python.org/downloads/');
  process.exit(1);
}
console.log(`✓ Using ${py}`);

const venvPython = venvBin('python');
const venvPip = venvBin('pip');

// ── 2. venv + deps ─────────────────────────────────────────────────────────
if (!fs.existsSync(venvPython)) {
  console.log('[1/3] Creating virtual environment...');
  run(`"${py}" -m venv "${path.join(PKG_ROOT, '.venv')}"`);
}

console.log('[2/3] Installing Python dependencies (first run only)...');
run(`"${venvPip}" install -q -r "${path.join(PKG_ROOT, 'requirements.txt')}"`, {
  env: process.env,
});

// ── 3. ffmpeg via imageio-ffmpeg (no system ffmpeg required) ──────────────
let ffmpegDir = null;
try {
  const exe = execSync(`"${venvPython}" -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"`, {
    stdio: ['ignore', 'pipe', 'ignore'],
  })
    .toString()
    .trim();
  if (exe) ffmpegDir = path.dirname(exe);
} catch (_) {
  /* imageio-ffmpeg missing is non-fatal; system ffmpeg may still work */
}
if (ffmpegDir) {
  console.log('✓ Using bundled ffmpeg (imageio-ffmpeg)');
} else {
  console.log('⚠ No bundled ffmpeg found; relying on system ffmpeg in PATH');
}

// ── 4. launch server ──────────────────────────────────────────────────────
const env = Object.assign({}, process.env, {
  HOST: host,
  PORT: String(port),
});
if (ffmpegDir) {
  env.PATH = ffmpegDir + path.delimiter + (env.PATH || '');
}
if (process.env.AGNES_API_KEY) {
  env.AGNES_API_KEY = process.env.AGNES_API_KEY;
}

console.log('[3/3] Starting service...');
console.log('');
console.log(`  Web UI will be at http://${host === '0.0.0.0' ? '127.0.0.1' : host}:${port}`);
console.log('  Press Ctrl+C to stop.');
console.log('');

const child = spawn(venvPython, ['server.py'], {
  cwd: PKG_ROOT,
  env,
  stdio: 'inherit',
});

child.on('exit', (code) => {
  process.exit(code === null ? 0 : code);
});

const shutdown = (sig) => {
  if (child.exitCode === null) child.kill(sig);
};
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

// ── auto-open browser ─────────────────────────────────────────────────────
// 轮询等待服务就绪（HTTP 200）后再打开浏览器，避免启动初期闪现"无法访问"
if (openBrowser) {
  const http = require('http');
  const url = `http://${host === '0.0.0.0' ? '127.0.0.1' : host}:${port}`;
  let attempts = 0;

  const openBrowserNow = () => {
    try {
      if (process.platform === 'darwin') execSync(`open "${url}"`);
      else if (process.platform === 'win32') execSync(`start "" "${url}"`);
      else execSync(`xdg-open "${url}"`);
    } catch (_) {
      /* browser open is best-effort */
    }
  };

  const scheduleNext = () => {
    if (++attempts > 120) return; // 约 60s 上限，超时不再尝试
    setTimeout(pollReady, 500);
  };

  const pollReady = () => {
    const req = http.get(url, (res) => {
      res.resume();
      if (res.statusCode >= 200 && res.statusCode < 500) openBrowserNow();
      else scheduleNext();
    });
    req.setTimeout(2000, () => {
      req.destroy();
      scheduleNext();
    });
    req.on('error', scheduleNext);
  };

  pollReady();
}
