#!/usr/bin/python3

import io
import os
import sys

import git
import git.index.fun as indexfun
import git.objects.fun as objfun

from git.util import bin_to_hex, stream_copy
from git.objects import Blob
from git.index.typ import BaseIndexEntry
from gitdb.base import IStream


# TODO: do not hardcode these
TP = "tp0"
CUAT = "2020_1"

# TODO: accept command line options
TPREPO = os.path.expanduser("~/fiuba/tprepo")
ALUREPO = os.path.expanduser("~/fiuba/alurepo")

# TODO: DEFINITELY do not hardcode these
USERNAMES = {
    "103457": "tomascosta3",
    "103740": "milognr",
    "104302": "angysaavedra",
    "105147": "juancebarberis",
    "105296": "nazaquintero",
}


# TODO: usar bare repos?


def overwrite_files(repo, tree, subdir=""):
    """Sobreescribe archivos en un repositorio con contenidos de otro árbol.

    Args:
      repo (git.Repo): repo destino.
      tree (git.Tree): árbol con los nuevos contenidos.
      prefix (string): subdirectorio del repositorio donde realizar el remplazo.

    Returns:
      el nuevo árbol raíz (git.Tree) del repositorio destino.
    """
    objdb = tree.repo.odb
    prefix = ""
    old_tree = repo.tree()

    if subdir:
        path = subdir.rstrip("/")
        prefix = f"{path}/"
        old_tree = old_tree.join(path)

    old_files = objfun.traverse_tree_recursive(repo.odb, old_tree.binsha, prefix)
    new_files = objfun.traverse_tree_recursive(objdb, tree.binsha, prefix)

    new_entries = merged_entries([], new_files)
    all_entries = merged_entries(old_files, new_files)

    # Copy new files into repository.
    for entry in new_entries:
        blob = io.BytesIO()
        stream_copy(objdb.stream(entry.binsha), blob)
        blob.seek(0)
        size = len(blob.getvalue())
        result = repo.odb.store(IStream(Blob.type, size, blob))
        assert result[0] == entry.binsha

    # Create tree with all entries (old and new) and return it.
    tree_binsha, _ = indexfun.write_tree_from_cache(
        all_entries, repo.odb, slice(0, len(all_entries))
    )
    return repo.tree(bin_to_hex(tree_binsha).decode("ascii"))


def merged_entries(old_traversal, new_traversal):
    ot = {e[2]: e for e in old_traversal}
    nt = {e[2]: e for e in new_traversal}
    merged_entries = []

    ot.update(nt)

    for _, (sha, mode, path) in sorted(ot.items()):
        merged_entries.append(BaseIndexEntry((mode, sha, 0, path)))

    return merged_entries


def update_repo(legajo, repo):
    """Actualiza el repositorio correspondiente a un legajo.

    La función examina las entregas en el repositorio global de entregas,
    y aplica las faltantes al repositorio destino.

    Args:
      legajo (string): el legado correspondiente al repositorio
      repo (git.Repo): el repositorio destino
    """
    print(f"Processing {legajo}")
    tprepo = git.Repo(TPREPO)
    tppath = f"{TP}/{CUAT}/{legajo}"
    branch = get_branch(repo, TP)
    newest_in_repo = branch.commit.authored_date
    pending_commits = []

    for commit in tprepo.iter_commits(paths=[tppath]):
        if commit.authored_date > newest_in_repo:  # XXX Not robust enough.
            pending_commits.append(commit)

    if not pending_commits:
        print(f"Nothing to do for {legajo}/{TP}", file=sys.stderr)
        # XXX
        repo.index.reset(working_tree=True)
        return
    else:
        n = len(pending_commits)
        print(f"Applying {n} commits to {legajo}/{TP}", file=sys.stderr)

    index = repo.index
    try:
        ghuser = USERNAMES[legajo]
    except KeyError:
        print(f"No username for {legajo}", file=sys.stderr)
        return
    else:
        author = git.Actor(ghuser, f"{ghuser}@users.noreply.github.com")

    branch.checkout()

    for commit in reversed(pending_commits):
        # Objeto Tree con los archivos de la entrega.
        entrega_tree = commit.tree.join(tppath)
        updated_tree = overwrite_files(repo, entrega_tree, TP)

        tz_hours = commit.author_tz_offset // 3600
        tz_minutes = commit.author_tz_offset % 3600 // 60
        authored_date = f"{commit.authored_date} {tz_hours:+03}{tz_minutes:02}"

        git.Commit.create_from_tree(
            repo,
            updated_tree,
            commit.message,
            head=True,
            author=author,
            author_date=authored_date,
            committer=author,
            commit_date=authored_date,
        )

        # XXX
        repo.index.reset(working_tree=True)


def get_branch(repo, branch_name):
    """Dado un repo, devolver la rama con ese nombre.
    """
    for branch in repo.branches:
        if branch.name == branch_name:
            return branch


def main():
    for repodir in os.listdir(ALUREPO):
        path = os.path.join(ALUREPO, repodir)
        try:
            repo = git.Repo(path)
        except git.exc.InvalidGitRepositoryError as ex:
            print(f"could not open {repodir!r}: {ex}", file=sys.stderr)
        else:
            # TODO: opportunistically return pull request URL.
            update_repo(repodir, repo)


if __name__ == "__main__":
    main()

# Local Variables:
# eval: (blacken-mode 1)
# End:
