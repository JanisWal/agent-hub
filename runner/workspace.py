"""The code of the projects and the work folder of every agent task (15.11.2026). Standard library only (git).

Layout under HUB_WORK_DIR (outside data/, same path inside and outside the runner, like the Claude folder):
    repos/<project>.git     the project's code, a bare repository with the branch main (made on first use)
    gitdirs/<task>.git      the git side of one task (owned by root, never mounted into a run)
    tasks/<task>/           the files of the task, the only folder a run sees (as /work), owned by the run user

Safety: a run can change anything in its folder, but it never sees .git. Git's own settings and hooks live in the
git dir, which only the runner can reach, so nothing a run writes can make the runner execute code when it commits
(core.hooksPath is switched off as well). The runner commits after each run and pushes the task's branch to the
project; after the user's approval it merges the branch into main (`merge`).
"""
import shutil
import subprocess
from pathlib import Path

GIT = ["git", "-c", "core.hooksPath=/dev/null", "-c", "safe.directory=*", "-c", "user.name=Agent-Hub",
       "-c", "user.email=agents@agent-hub.local", "-c", "commit.gpgsign=false", "-c", "core.fsmonitor=false"]
# What running the code leaves behind (first real run, 15.11.2026: __pycache__ ended up in the project). Written to the
# task's git dir on every commit; the project's own .gitignore counts in addition.
NEVER_COMMIT = ("__pycache__/", "*.pyc", ".pytest_cache/", ".mypy_cache/", "node_modules/", ".DS_Store", ".coverage",
                "coverage/", ".npm/")
TEST_SCRIPT = "hub-test.sh"   # the project's tests: the hub runs it after the programmer (runner.py, launcher.build_test_command)
MAX_DIFF = 60000              # characters of a task's change that go to the hub (tester, reviewer, approval)
MAX_STAT = 4000


class Workspace:
    def __init__(self, base: str | Path):
        self.base = Path(base)

    def repo(self, project_id: int) -> Path:
        return self.base / "repos" / f"{int(project_id)}.git"

    def gitdir(self, task_id: int) -> Path:
        return self.base / "gitdirs" / f"{int(task_id)}.git"

    def tree(self, task_id: int) -> Path:
        return self.base / "tasks" / str(int(task_id))

    def _git(self, *args: str, git_dir: Path | None = None, work: Path | None = None,
             check: bool = True) -> subprocess.CompletedProcess:
        where = ([f"--git-dir={git_dir}"] if git_dir else []) + ([f"--work-tree={work}"] if work else [])
        return subprocess.run([*GIT, *where, *args], capture_output=True, text=True, check=check, timeout=300)

    def ensure_repo(self, project_id: int) -> Path:
        """The project's repository; a new one starts with an empty first commit on main."""
        repo = self.repo(project_id)
        if not (repo / "HEAD").is_file():
            repo.parent.mkdir(parents=True, exist_ok=True)
            self._git("init", "-q", "--bare", "-b", "main", str(repo))
            tree = subprocess.run([*GIT, f"--git-dir={repo}", "mktree"], input="", capture_output=True, text=True,
                                  check=True).stdout.strip()
            commit = self._git("commit-tree", tree, "-m", "Start", git_dir=repo).stdout.strip()
            self._git("update-ref", "refs/heads/main", commit, git_dir=repo)
        return repo

    def prepare(self, task_id: int, project_id: int, branch: str) -> Path:
        """The task's folder on its branch (made from main the first time; kept between the rounds)."""
        repo, git_dir, tree = self.ensure_repo(project_id), self.gitdir(task_id), self.tree(task_id)
        if not (git_dir / "HEAD").is_file():
            git_dir.parent.mkdir(parents=True, exist_ok=True)
            self._git("init", "-q", "--bare", str(git_dir))
            self._git("config", "core.bare", "false", git_dir=git_dir)
            self._git("remote", "add", "origin", str(repo), git_dir=git_dir)
            self._git("fetch", "-q", "origin", git_dir=git_dir)
            tree.mkdir(parents=True, exist_ok=True)
            remote = self._git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}", git_dir=git_dir,
                               check=False).returncode == 0
            self._git("checkout", "-q", "-B", branch, f"origin/{branch}" if remote else "origin/main",
                      git_dir=git_dir, work=tree)
        tree.mkdir(parents=True, exist_ok=True)
        return tree

    def commit(self, task_id: int, branch: str, message: str) -> bool:
        """Commit what the run changed and push the branch to the project. False if nothing changed."""
        git_dir, tree = self.gitdir(task_id), self.tree(task_id)
        (git_dir / "info").mkdir(exist_ok=True)              # outside the folder: a run can not change it
        exclude = git_dir / "info" / "exclude"
        exclude.write_text("\n".join(NEVER_COMMIT) + "\n")
        self._git("add", "-A", git_dir=git_dir, work=tree)
        # Caches committed before this list existed stay tracked otherwise (15.11.2026); only what the list names.
        tracked = self._git("ls-files", "-z", "-c", "-i", f"--exclude-from={exclude}", git_dir=git_dir,
                            work=tree).stdout.split("\0")
        if any(tracked):
            self._git("rm", "-q", "-r", "--cached", "--", *[t for t in tracked if t], git_dir=git_dir, work=tree)
        if self._git("diff", "--cached", "--quiet", git_dir=git_dir, work=tree, check=False).returncode == 0:
            return False
        self._git("commit", "-q", "-m", message, git_dir=git_dir, work=tree)
        self._git("push", "-q", "origin", f"HEAD:refs/heads/{branch}", git_dir=git_dir)
        return True

    def diff(self, task_id: int) -> tuple[str, str]:
        """(stat, patch) of what the task changed against main: the files with their +/- lines and the change itself
        (cut to MAX_STAT / MAX_DIFF characters). The tester, the reviewer and the approval read it."""
        git_dir, tree = self.gitdir(task_id), self.tree(task_id)
        self._git("fetch", "-q", "origin", git_dir=git_dir)
        base = ["diff", "--no-color", "--no-ext-diff", "-M", "origin/main...HEAD"]
        stat = self._git(*base[:-1], "--stat=120", base[-1], git_dir=git_dir, work=tree).stdout
        patch = self._git(*base, git_dir=git_dir, work=tree).stdout
        cut = lambda text, n: text if len(text) <= n else text[:n] + "\n[... cut]\n"
        return cut(stat, MAX_STAT), cut(patch, MAX_DIFF)

    def has_tests(self, task_id: int) -> bool:
        script = self.tree(task_id) / TEST_SCRIPT
        return script.is_file() and not script.is_symlink()

    def reset(self, task_id: int) -> None:
        """Back to the last commit after the tests ran: files they changed or left behind go (what NEVER_COMMIT names,
        such as node_modules, stays for the next round)."""
        git_dir, tree = self.gitdir(task_id), self.tree(task_id)
        self._git("checkout", "-q", "--", ".", git_dir=git_dir, work=tree, check=False)
        self._git("clean", "-q", "-f", "-d", git_dir=git_dir, work=tree, check=False)

    def merge(self, task_id: int, project_id: int, branch: str) -> bool:
        """Bring the approved branch into main. Fast-forward when main has not moved; otherwise main is merged into
        the branch first (in the task's folder) and the result goes to main. False on a conflict (nothing changes)."""
        repo = self.ensure_repo(project_id)
        if self._git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", git_dir=repo, check=False).returncode:
            return True                                    # the agents committed nothing: nothing to merge
        ahead = self._git("merge-base", "--is-ancestor", "refs/heads/main", f"refs/heads/{branch}", git_dir=repo,
                          check=False).returncode == 0
        if not ahead:
            git_dir, tree = self.gitdir(task_id), self.tree(task_id)
            if not (git_dir / "HEAD").is_file():
                return False
            self._git("fetch", "-q", "origin", git_dir=git_dir)
            if self._git("merge", "-q", "--no-edit", "origin/main", git_dir=git_dir, work=tree, check=False).returncode:
                self._git("merge", "--abort", git_dir=git_dir, work=tree, check=False)
                return False
            self._git("push", "-q", "origin", f"HEAD:refs/heads/{branch}", git_dir=git_dir)
        self._git("update-ref", "refs/heads/main", f"refs/heads/{branch}", git_dir=repo)
        return True

    def remove(self, task_id: int) -> bool:
        """The task is over: its folder and its git side go (the branch stays in the project's repository). True
        if nothing of them is left."""
        return self._delete(self.tree(task_id), self.gitdir(task_id))

    def remove_project(self, project_id: int) -> bool:
        """The project was deleted: its code repository goes for good. True if nothing of it is left."""
        return self._delete(self.repo(project_id))

    @staticmethod
    def _delete(*paths: Path) -> bool:
        for path in paths:
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
        return not any(path.exists() for path in paths)
