# Researching recommendations from online lists

Goal: a `data/web_recommendations.json` (format in `schemas.md`) that reflects what people currently recommend for the user's role, filtered to what the preset lacks.

## Contents
- Steps
- Choosing queries
- Judging sources
- Verifying names
- Writing the file

## Steps

1. Read the target preset (`presets.py show NAME`) so you know what is already covered and which roles matter.
2. Search for current lists for each role. Check the current year: lists from three or more years ago recommend dead or renamed packages.
3. Collect candidate tools. Prefer ones that appear in at least two independent sources.
4. Verify each name against Homebrew (below). Drop anything that does not resolve.
5. Write the JSON and run `scripts/setup.sh recommend --preset NAME`.
6. Tell the user what you found, how many candidates were dropped, and which sources you used.

## Choosing queries

Search for the role plus Homebrew, not just the role. Useful shapes:

- "best Homebrew casks for <role> <current year>"
- "essential Homebrew formulae <language or platform>"
- "awesome mac <role>" (curated GitHub lists)
- public Brewfiles or dotfiles repos from people in the same role (these often yield `brew "x"` / `cask "x"` lines that `recommend.py --source <url>` can mine directly)

For a photographer: RAW workflow, film scanning, metadata and color tools. For an Android engineer: adb tooling, decompilers, device mirroring, Gradle and JDK management. Match the user's actual stack rather than a generic list.

## Judging sources

- Good: maintained GitHub lists, recent Brewfiles from active developers, official project docs, recent roundups with named authors.
- Weak: undated listicles, SEO pages that rank 40 apps with no reasoning, anything that is clearly affiliate-driven.
- One source is thin evidence. Mark tools that only one source mentioned as tier 3 unless you have your own reason to rank them higher.

## Verifying names

On a Mac with Homebrew: `brew info --formula <name>` or `brew info --cask <name>`. Without it, `recommend.py` verifies later on the Mac and drops unknown names, but check anyway when you can: the same app is often a formula in one list and a cask in another, and casks get renamed.

## Writing the file

- Paraphrase the reason in one short sentence of your own. Do not paste text from articles.
- Put each source URL you actually relied on in `sources`. The script counts distinct entries to weight agreement, so do not pad it.
- Leave `tier` out unless you have a concrete reason to override the source-count rule for this user (for example, a tool that directly matches something they already use heavily).
- Do not include things the user excluded or already has; the script removes them, but fewer junk entries make a better file.
