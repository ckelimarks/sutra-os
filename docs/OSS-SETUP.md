# OSS Repository Setup (One-time)

Steps to establish `sutra-os` as the official public repository and set up the sync workflow.

---

## Prerequisites

- [ ] `sutra-build` is consolidated (run the docconsolidator agent first)
- [ ] GitHub personal account or org ready
- [ ] `~/Downloads/sutra-os/` directory exists (clone from GitHub, or create new)

---

## Step 1: Create the public repository (if new)

On GitHub:

1. Create a new public repo: `sutra-os`
2. Initialize with README (GitHub will offer this)
3. Clone locally:
   ```bash
   git clone https://github.com/[your-org]/sutra-os.git ~/Downloads/sutra-os
   ```

---

## Step 2: Initialize sutra-os with sanitized content

```bash
cd ~/Downloads/sutra-os

# Clear any placeholder content
git rm -r . || true
git commit -m "Clear placeholder" || true

# Copy sanitized content from sutra-build
cd <user>/project/Projects/prototypes/sutra-build
./sanitize-and-push.sh

# This will diff and push. Confirm when prompted.
```

---

## Step 3: Verify sutra-os structure

After the first sync, `sutra-os` should have:

```
sutra-os/
├── README.md
├── INFRA.md
├── API.md
├── docs/
│   ├── PRD.md
│   ├── ROADMAP.md
│   ├── SESSION-JSONL.md
│   ├── TAXONOMY.md
│   ├── UI-GLOSSARY.md
│   └── OSS-SYNC-WORKFLOW.md
├── server/
├── web/
├── LICENSE              ← add if desired
└── (no CLAUDE.md, no ARCHITECTURE.md, no archive/)
```

Verify by checking GitHub. The repo should be public-ready.

---

## Step 4: Protect main branch (optional but recommended)

On GitHub Settings → Branches:

- Enable "Require pull request reviews before merging" (1 review)
- Enable "Require status checks to pass"

This prevents accidental direct pushes. All changes come from `sanitize-and-push.sh`, which is the intended flow.

---

## Step 5: Set up GitHub issue templates (optional)

Create `.github/ISSUE_TEMPLATE/bug.md`:

```markdown
---
name: Bug Report
about: Report a bug in Sutra
---

## Description
<!-- What's broken? -->

## Steps to reproduce
<!-- How do we see the bug? -->

## Expected behavior
<!-- What should happen? -->

## Environment
- OS: 
- Browser: 
- Sutra commit: 

## Notes
<!-- Any other context? -->
```

This helps users file better reports.

---

## Step 6: Document the contribution flow

Create `CONTRIBUTING.md` in `sutra-os`:

```markdown
# Contributing to Sutra OS

Thanks for your interest! We welcome issues and pull requests.

## Filing a bug

1. Check existing issues first (might already be fixed)
2. File a detailed bug report with steps to reproduce
3. We'll triage and may ask clarifying questions

## Submitting a PR

1. Fork the repo
2. Create a feature branch: `git checkout -b fix/your-issue`
3. Make your changes
4. Submit a PR with a clear description of the problem and solution
5. Maintainer will review and may ask for changes

**Note:** This is a mirror of our internal `sutra-build` repo. Your fix will be ported into the canonical source and re-synced back to this repo automatically.

## Roadmap

See `docs/ROADMAP.md` for what's in progress and planned.
```

---

## Step 7: Test the sync workflow

Make a small change in `sutra-build` (e.g., typo in README) and push it:

```bash
cd <user>/project/Projects/prototypes/sutra-build
# Make a small change to README.md
echo "# Test" >> README.md
git add README.md
git commit -m "Test sync"
./sanitize-and-push.sh
# Confirm the diff includes your change
# Verify on GitHub that the change landed in sutra-os
```

If the change appears in `sutra-os` on GitHub, the sync is working.

---

## Step 8: Document the OSS policy internally

Add to `sutra-build/CLAUDE.md`:

```markdown
## Public Repository (sutra-os)

Sutra has a public open-source mirror at https://github.com/[your-org]/sutra-os.

**Policy:**
- All development happens in `sutra-build/` (this repo)
- `sutra-os` is a derived artifact (read-only public)
- Use `./sanitize-and-push.sh` to sync changes
- Issues/PRs from OSS are ported to sutra-build, fixed, and re-synced

See `docs/OSS-SYNC-WORKFLOW.md` for detailed procedures.
```

---

## Ongoing maintenance

After setup, the only recurring task is:

1. **When shipping a feature:** Run `./sanitize-and-push.sh`
2. **When an OSS issue comes in:** Fix in sutra-build, re-sync
3. **When an OSS PR comes in:** Port intent to sutra-build, re-sync

---

## Rollback (if needed)

If something goes wrong:

```bash
cd ~/Downloads/sutra-os
git log --oneline
git revert [bad-commit]
git push origin main
```

Then re-run `./sanitize-and-push.sh` to resync from sutra-build (will overwrite).

---

*Setup complete. sutra-os is now a derived artifact. Only sync via `sanitize-and-push.sh`.*
