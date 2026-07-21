# Reproducible local deployment

The portfolio v1 deployment target is one ROS 2 Jazzy workstation. Project 1 and Project 2 remain separate
workspaces and are overlaid at runtime. The MCP server is local stdio only; MiMo credentials stay in the current
shell; learned RAG is offline and pinned to the locally cached BGE-M3 revision.

## Environment boundaries

- ROS processes use the system Jazzy Python environment.
- The MCP protocol process uses `~/robot_agent_mcp_env` and the exact versions in `mcp-requirements.lock`.
- Learned retrieval uses `~/qwen_vl_env`; it receives no proxy variables and is forced offline.
- Its explicit import roots are `src/robot_rag` and Ubuntu's `/usr/lib/python3/dist-packages` for the declared
  `python3-jsonschema` dependency; arbitrary interactive-shell `PYTHONPATH` entries are not inherited.
- Generated Skill candidates live under `~/.ros/robot_agent/skill_candidates`, outside the source tree.
- Experiment sources and report artifacts use separate allowlisted roots.
- API keys, Ed25519 private keys, Registry databases, approvals and full traces are not committed.

## One-shot verification

Run `scripts/final_verify.sh`. It builds all packages, runs the complete test suite, checks the colcon result,
executes the real local 10-requirement Skill Author build/test evaluation, then executes the 42-case frozen
final policy evaluation. Report bundles are written under `~/.ros/robot_agent/skill_author_evaluation_v1` and
`~/.ros/robot_agent/final_evaluation_v1`.

The deterministic final evaluation does not replace the separately frozen live MiMo, MCP and ROS simulation
evidence. A release claim must name which boundary produced each result.
