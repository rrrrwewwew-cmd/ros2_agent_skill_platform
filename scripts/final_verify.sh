#!/usr/bin/env bash
set -eo pipefail

workspace="${ROBOT_AGENT_WS:-$HOME/robot_agent_ws}"
output="${ROBOT_AGENT_EVAL_OUTPUT:-$HOME/.ros/robot_agent/final_evaluation_v1}"
author_output="${ROBOT_AGENT_AUTHOR_EVAL_OUTPUT:-$HOME/.ros/robot_agent/skill_author_evaluation_v1}"

cd "$workspace"
source /opt/ros/jazzy/setup.bash

colcon build --symlink-install --event-handlers console_direct+
source install/setup.bash
set -u
colcon test --event-handlers console_direct+
colcon test-result --verbose

ros2 run robot_skill_author evaluate_skill_author \
  --repository-root "$workspace" \
  --output-dir "$author_output"

ros2 run safe_agent_eval run_final_evaluation \
  --repository-root "$workspace" \
  --output-dir "$output"
