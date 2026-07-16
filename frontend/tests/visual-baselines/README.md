# Visual regression assets

This directory contains self-contained assets used to detect unintended changes in the implemented frontend. Versioned subdirectories may contain geometry/computed-style manifests and reference screenshots consumed by Playwright.

These files are test fixtures, not the authority for future design decisions. A UI task must compare against the external prototype source supplied for that task. Never store that source's absolute local path here.

Only update these assets after the external source has been verified and a design revision has been deliberately implemented. Do not replace screenshots, relax geometry, or expand tolerances merely to make a failing implementation pass.
