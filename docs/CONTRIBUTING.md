# Contributing to dune-dscs

## Reporting Problems

Open an [issue](https://github.com/DUNE/dune-dscs/issues) with enough detail to reproduce your error from scratch: what you ran, what you expected, and what actually happened. Include the name of the machine you ran on (e.g., `dunegpvm09.fnal.gov`, personal laptop, etc.) as well as any relevant python/dependency versions (`uv pip list` and/or `uv run python --version`).

## Development Workflow

The development workflow for `dune-dscs` is based on the [shared repository model](https://docs.github.com/en/pull-requests/reference/pull-requests#shared-repository-model). The "common" branch (`develop`, in our case) is intended to be a stable starting point for development work, and is therefore protected. This means you can't make changes directly to `develop`, but instead must make changes on a feature branch and then submit a pull request when your changes are ready for review.

1. Create a feature branch from the latest `develop` branch: while on the `develop` branch, run
   ```bash
   git pull # Make sure your develop branch is up-to-date
   git switch -c username/my_new_feature
   ```
   Choose a branch name that is concise but describes the nature of the change. Note you can also use `git checkout -b` instead of `git switch`, particularly if using git v2.22 or older.

2. Make your changes, check them using `ruff` and `pytest`, and commit them to the branch: 
   ```bash
   uv run ruff check src tests  # Catches common mistakes
   uv run pytest tests          # Runs all tests defined in the tests/ directory
   git add <changed_files>
   git commit -m "Here's what I changed."
   ```
   If `ruff` reports problems, you can either fix them by hand or run `uv run ruff check --fix`. 
   
   Use `git status` to see which file(s) you've changed and `git diff` to confirm the changes you're committing are what you expect. Make sure to update any relevant documentation in the `docs/` folder.

3. Push your branch to GitHub: 
   ```bash
   git push -u origin username/my_new_feature
   ```

4. Open a [pull request](https://github.com/DUNE/dune-dscs/pulls) and assign an appropriate reviewer. Merging new code into `develop` requires at least one approval from a reviewer. If you're unsure who to assign, ask in the #dscs-all Slack channel. The "base" branch is whichever branch you want your changes merged into (usually `develop`). The "compare" branch is your branch containing the proposed changes. In the pull request, include a description of your changes: what problem this solves, how reviewers can test it, how others can use it, etc.

   Pull requests should be small and focused on one change. Smaller pull requests are easier to review and likely to get merged faster. Reviewers may ask for a large pull request to be split up before reviewing it.

## Style Notes

Python code should follow [PEP 8](https://peps.python.org/pep-0008/) conventions.

Pull requests run Ruff on maintained Python code. Archived scripts and generated
protobuf bindings are excluded. The WIB binding requires protobuf 7.36.2 or newer.