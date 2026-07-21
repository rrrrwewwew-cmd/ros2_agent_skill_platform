# Return Home Safely

Use this controlled composite Skill only after a home pose has been supplied and explicitly approved.

## Evidence order

1. Require fresh robot health and safety-monitor evidence.
2. Verify the persisted `water_puddle` semantic-map record and content hash.
3. Preview the exact home route and require an active Keepout plus positive clearance.
4. Execute the preview-bound Nav2 goal; revalidation and cancellation remain active during motion.

The workflow cannot directly write velocity commands. Missing semantic evidence, an unsafe route, a stale hash,
or a failed navigation postcondition stops the workflow and is retained in the Runtime Trace.
