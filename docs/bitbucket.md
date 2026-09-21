# Bitbucket integration

Bitbucket remains a supported SCM provider in v2.0.2, but normal publication is provider-neutral and driven by `agentctl run` after candidate verification and AI review.

Configure a project with:

```bash
scmctl configure --provider bitbucket --remote origin --base-branch main
scmctl doctor
```

Authentication remains environment-based (`BITBUCKET_ACCESS_TOKEN`, or `BITBUCKET_API_TOKEN` with `BITBUCKET_EMAIL`). Credentials are not stored in the project manifest. The compatibility `bitbucket-pr` command remains available for diagnostics/legacy use, but new workflow items do not require a separate human PR-creation approval. Merge remains human-gated.
