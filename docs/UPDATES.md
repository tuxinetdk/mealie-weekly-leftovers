# Update behavior

The Update Guard separates **candidate preparation** from **activation**.

Candidate preparation runs while the existing Mealie container remains online:

1. detect stable upstream release;
2. download exact source tag;
3. run patch compatibility check;
4. apply the patch;
5. build the custom image.

Activation begins only after a candidate image exists:

1. stop the Mealie application container;
2. create and verify PostgreSQL + `/app/data` backup;
3. update the pinned Mealie version;
4. recreate the application from the custom image;
5. wait up to the configured health timeout;
6. retain the backup on success;
7. capture diagnostics and roll back on failure.

The guard never runs `apt upgrade`, `pip install`, or `yarn install` inside a running Mealie container. Container updates are image replacements.

A long candidate build therefore does not mean a long application outage: the old Mealie remains online while the candidate is being prepared.
