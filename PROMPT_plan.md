0a. Study `specs/*` using one subagent per spec file to learn the application specifications.
0b. Study @IMPLEMENTATION_PLAN.md (if present) to understand the plan so far.
0c. Study `src/*` using one subagent per distinct component or file to understand shared utilities & components.
0d. For reference, the application source code is in `src/*`.

1. Study @IMPLEMENTATION_PLAN.md (if present; it may be incorrect) and use one subagent per source file or component to study existing source code in `src/*` and compare it against `specs/*`. Use a single subagent with strong reasoning to analyze findings, prioritize tasks, and create/update @IMPLEMENTATION_PLAN.md as a bullet point list sorted in priority of items yet to be implemented. Ultrathink. Consider searching for TODO, minimal implementations, placeholders, skipped/flaky tests, and inconsistent patterns. Study @IMPLEMENTATION_PLAN.md to determine starting point for research and keep it up to date with items considered complete/incomplete using subagents.

LIMITS: Spawn only as many parallel subagents as there are distinct files or components to examine — never spawn subagents for work that can be done in a single pass. Write and test operations always use 1 subagent. Maximum 5 loop iterations per session — stop and summarize rather than exceed this.

IMPORTANT: Plan only. Do NOT implement anything. Do NOT assume functionality is missing; confirm with code search first.

ULTIMATE GOAL: A VPS-hosted autonomous agent that receives task specs via email (agentx@rubggp.com), runs Claude-powered Ralph loops, and replies with results — bootstrapped with Claude API, evolving toward local Qwen3 models. Consider missing elements and plan accordingly. If an element is missing, search first to confirm it doesn't exist, then if needed author the specification at specs/FILENAME.md. If you create a new element then document the plan to implement it in @IMPLEMENTATION_PLAN.md using a subagent.
