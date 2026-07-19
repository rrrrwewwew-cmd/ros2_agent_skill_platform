# `navigate_to_approved_pose` evidence

- `rbot_live_simulation_v1.json` freezes the first controlled-motion rbot
  simulation result that passed preflight, navigation, Keepout monitoring, and
  physical postconditions.
- `governed_release_v1.json` records human release approval, Ed25519
  activation, one-time execution approval consumption, Runtime state, and
  physical postconditions.

No private key, Registry database, or unredacted local credential belongs in
this directory.
