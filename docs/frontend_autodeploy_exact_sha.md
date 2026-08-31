# Exact-SHA frontend deployment — HappyFox

HappyFox no longer has a separate legacy frontend release source. The Mini App is released from the same verified `foxgen/main` SHA as the backend.

Required evidence:

```text
PR head SHA -> CI green
main merge SHA -> main CI green
Deploy HappyFox production target -> same verified main SHA
Mini App revision -> deployment SHA
```

Canonical instructions: `production-deployment.md` and `production_auto_deploy.md`.

Do not deploy frontend files from an old NEUROMIX/Tanya branch/profile independently of the verified HappyFox release unless an explicit emergency procedure documents the divergence and restores exact-SHA consistency immediately afterward.
