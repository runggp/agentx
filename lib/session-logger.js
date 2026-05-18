#!/usr/bin/env node
/**
 * Ralph Session Logger
 *
 * Parses Claude stream-json output and appends structured iteration data
 * to a per-session JSON log file at logs/sessions/<session-id>.json.
 *
 * The log file is readable by future agent iterations to understand
 * what happened in previous sessions: cost, tokens, tools, files changed.
 *
 * Usage (called from loop.sh after each iteration):
 *   node session-logger.js init --session-id <id> --branch <b> \
 *     --original-branch <ob> --mode <m> --model <mdl> \
 *     --max-iterations <n> --head-at-start <hash>
 *
 *   node session-logger.js iteration --session-id <id> --iteration <n> \
 *     --model <mdl> --duration-ms <ms> --prev-commit <hash> \
 *     <stream-json-file>
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const LOGS_DIR = path.join(process.cwd(), 'logs', 'sessions');

function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next !== undefined && !next.startsWith('--')) {
        args[key] = next;
        i++;
      } else {
        args[key] = true;
      }
    } else {
      args._.push(a);
    }
  }
  return args;
}

function sessionPath(sessionId) {
  return path.join(LOGS_DIR, `${sessionId}.json`);
}

function readSession(sessionId) {
  const p = sessionPath(sessionId);
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
}

function writeSession(sessionId, data) {
  fs.mkdirSync(LOGS_DIR, { recursive: true });
  const p = sessionPath(sessionId);
  fs.writeFileSync(p, JSON.stringify(data, null, 2) + '\n', 'utf8');
}

function gitHead() {
  try {
    return execSync('git rev-parse HEAD', { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString().trim();
  } catch {
    return null;
  }
}

function gitFilesChanged(fromCommit) {
  if (!fromCommit) return [];
  try {
    const out = execSync(
      `git diff --name-only ${fromCommit}..HEAD`,
      { stdio: ['ignore', 'pipe', 'ignore'] }
    ).toString().trim();
    return out ? out.split('\n') : [];
  } catch {
    return [];
  }
}

function parseStreamJson(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    return { model: null, cost_usd: null, input_tokens: null, output_tokens: null, tools_called: [] };
  }

  const lines = fs.readFileSync(filePath, 'utf8').split('\n');
  let model = null;
  let cost_usd = null;
  let input_tokens = null;
  let output_tokens = null;
  const toolsSeen = new Set();

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    let data;
    try {
      data = JSON.parse(trimmed);
    } catch {
      continue;
    }

    if (data.type === 'message_start' && data.message?.model) {
      model = data.message.model;
      if (data.message.usage) {
        if (data.message.usage.input_tokens != null) {
          input_tokens = data.message.usage.input_tokens;
        }
      }
    }

    if (data.type === 'message_delta' && data.usage) {
      if (data.usage.output_tokens != null) {
        output_tokens = data.usage.output_tokens;
      }
    }

    if (data.type === 'result') {
      if (data.cost_usd != null) cost_usd = parseFloat(data.cost_usd);
      if (data.usage) {
        if (data.usage.input_tokens != null) input_tokens = data.usage.input_tokens;
        if (data.usage.output_tokens != null) output_tokens = data.usage.output_tokens;
      }
    }

    if (data.type === 'tool_use' && data.name) {
      toolsSeen.add(data.name);
    }

    if (data.type === 'content_block_start' &&
        data.content_block?.type === 'tool_use' &&
        data.content_block?.name) {
      toolsSeen.add(data.content_block.name);
    }
  }

  return {
    model,
    cost_usd,
    input_tokens,
    output_tokens,
    tools_called: Array.from(toolsSeen),
  };
}

function cmdInit(args) {
  const sessionId = args['session-id'];
  if (!sessionId) {
    console.error('[session-logger] --session-id required for init');
    process.exit(1);
  }

  const session = {
    session_id: sessionId,
    branch: args['branch'] || null,
    original_branch: args['original-branch'] || null,
    mode: args['mode'] || 'build',
    model: args['model'] || null,
    max_iterations: args['max-iterations'] ? parseInt(args['max-iterations'], 10) : null,
    started_at: new Date().toISOString(),
    head_at_start: args['head-at-start'] || gitHead(),
    iterations: [],
  };

  writeSession(sessionId, session);
  console.log(`[session-logger] session initialized: logs/sessions/${sessionId}.json`);
}

function cmdCheckSpend(args) {
  const sessionId = args['session-id'];
  if (!sessionId) {
    console.error('[session-logger] --session-id required for check-spend');
    process.exit(1);
  }

  const session = readSession(sessionId);
  if (!session) {
    console.error(`[session-logger] session file not found: ${sessionPath(sessionId)}`);
    process.exit(1);
  }

  const total = session.iterations.reduce((sum, it) => {
    return sum + (it.cost_usd != null ? it.cost_usd : 0);
  }, 0);

  const ceiling = args['ceiling'] != null ? parseFloat(args['ceiling']) : null;
  const totalStr = `$${total.toFixed(4)}`;
  const ceilStr = ceiling != null ? ` (ceiling: $${ceiling.toFixed(4)})` : '';
  const exceeded = ceiling != null && total >= ceiling;
  const status = exceeded ? 'EXCEEDED' : 'WITHIN';

  console.log(`[session-logger] spend: ${totalStr}${ceilStr} — ${status}`);

  if (exceeded) process.exit(2);
}

function cmdIteration(args) {
  const sessionId = args['session-id'];
  const iterNum = args['iteration'] ? parseInt(args['iteration'], 10) : null;
  const durationMs = args['duration-ms'] ? parseInt(args['duration-ms'], 10) : null;
  const prevCommit = args['prev-commit'] || null;
  const streamFile = args._[0] || null;

  if (!sessionId) {
    console.error('[session-logger] --session-id required for iteration');
    process.exit(1);
  }

  const session = readSession(sessionId);
  if (!session) {
    console.error(`[session-logger] session file not found: ${sessionPath(sessionId)}`);
    process.exit(1);
  }

  const streamData = parseStreamJson(streamFile);
  const headCommit = gitHead();
  const filesChanged = gitFilesChanged(prevCommit);

  const iteration = {
    iteration: iterNum,
    timestamp: new Date().toISOString(),
    model: streamData.model || args['model'] || session.model,
    cost_usd: streamData.cost_usd,
    input_tokens: streamData.input_tokens,
    output_tokens: streamData.output_tokens,
    tools_called: streamData.tools_called,
    files_changed: filesChanged,
    head_commit: headCommit,
    duration_ms: durationMs,
  };

  session.iterations.push(iteration);
  writeSession(sessionId, session);

  const cost = iteration.cost_usd != null ? `$${iteration.cost_usd.toFixed(4)}` : 'n/a';
  const tokens = iteration.input_tokens != null
    ? `${iteration.input_tokens}in/${iteration.output_tokens ?? 0}out`
    : 'n/a';
  console.log(
    `[session-logger] iteration ${iterNum} logged — cost: ${cost}, tokens: ${tokens}, ` +
    `tools: ${iteration.tools_called.length}, files: ${iteration.files_changed.length}`
  );
}

function cmdReport(args) {
  const last = args['last'] ? parseInt(args['last'], 10) : 5;

  if (!fs.existsSync(LOGS_DIR)) {
    console.log('## Prior Session Audit Trail\n\nNo sessions logged yet.');
    return;
  }

  const sessions = fs.readdirSync(LOGS_DIR)
    .filter(f => f.endsWith('.json'))
    .map(f => {
      try {
        return JSON.parse(fs.readFileSync(path.join(LOGS_DIR, f), 'utf8'));
      } catch {
        return null;
      }
    })
    .filter(Boolean)
    .sort((a, b) => new Date(b.started_at) - new Date(a.started_at));

  if (sessions.length === 0) {
    console.log('## Prior Session Audit Trail\n\nNo sessions logged yet.');
    return;
  }

  const totalCost = sessions.reduce((sum, s) =>
    sum + s.iterations.reduce((s2, it) => s2 + (it.cost_usd != null ? it.cost_usd : 0), 0), 0);
  const totalIters = sessions.reduce((sum, s) => sum + s.iterations.length, 0);

  const toolCounts = {};
  for (const s of sessions) {
    for (const it of s.iterations) {
      for (const tool of (it.tools_called || [])) {
        toolCounts[tool] = (toolCounts[tool] || 0) + 1;
      }
    }
  }
  const topTools = Object.entries(toolCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([name, count]) => `${name} (${count}\xd7)`)
    .join(', ');

  const lines = [
    '## Prior Session Audit Trail',
    '',
    `**${sessions.length} session(s) logged.** Total spend: $${totalCost.toFixed(4)}. Total iterations: ${totalIters}.`,
    '',
    `Recent sessions (newest first, showing up to ${last}):`,
  ];

  for (const s of sessions.slice(0, last)) {
    const date = s.started_at ? s.started_at.slice(0, 16).replace('T', ' ') : 'unknown';
    const iters = s.iterations.length;
    const cost = s.iterations.reduce((sum, it) => sum + (it.cost_usd != null ? it.cost_usd : 0), 0);
    const filesChanged = s.iterations.reduce((sum, it) => sum + (it.files_changed || []).length, 0);
    const label = s.branch || s.session_id;
    lines.push(`- ${date} | ${label} | ${iters} iter(s) | $${cost.toFixed(4)} | ${filesChanged} file(s) changed`);
  }

  if (topTools) {
    lines.push('');
    lines.push(`Top tools: ${topTools}`);
  }

  console.log(lines.join('\n'));
}

function main() {
  const [, , cmd, ...rest] = process.argv;
  const args = parseArgs(rest);

  switch (cmd) {
    case 'init':
      cmdInit(args);
      break;
    case 'iteration':
      cmdIteration(args);
      break;
    case 'check-spend':
      cmdCheckSpend(args);
      break;
    case 'report':
      cmdReport(args);
      break;
    default:
      console.error(`[session-logger] unknown command: ${cmd}`);
      console.error('Usage: session-logger.js <init|iteration|check-spend|report> [options] [stream-json-file]');
      process.exit(1);
  }
}

main();
