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
        self._git("add", "-A", git_dir=git_dir, work=tree)
        if self._git("diff", "--cached", "--quiet", git_dir=git_dir, work=tree, check=False).returncode == 0:
            return False
        self._git("commit", "-q", "-m", message, git_dir=git_dir, work=tree)
        self._git("push", "-q", "origin", f"HEAD:refs/heads/{branch}", git_dir=git_dir)
        return True

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

    def remove(self, task_id: int) -> None:
        """The task is over: its folder and its git side go (the branch stays in the project's repository)."""
        for path in (self.tree(task_id), self.gitdir(task_id)):
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
