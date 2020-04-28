#!/usr/bin/python3

"""Script/módulo para sincronizar las entregas con repositorios individuales.

Uso como script:

  $ ./pull_requests.py --tp <TP_ID> <alurepo>...

donde TP_ID es el TP a sincronizar ("tp0", "vector", etc.). Se puede
especificar la ubicación del checkout de algoritmos-rw/algo2_entregas
con la opción --entregas-repo.
"""

import argparse
import datetime
import io
import os
import pathlib
import sys

import git
import git.index.fun as indexfun
import git.objects.fun as objfun

from git.util import bin_to_hex, stream_copy
from git.objects import Blob
from git.index.typ import BaseIndexEntry
from gitdb.base import IStream


# Default si no se pasa uno por línea de comandos.
ENTREGAS_REPO = os.path.expanduser("~/fiuba/tprepo")

# Default si no se especifica con --cuatri.
CUATRIMESTRE = "2020_1"


def parse_args():
    """Parse command line options and arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "repos",
        metavar="alurepo",
        nargs="+",
        help="repositorio nombrado con el legajo asociado",
    )
    parser.add_argument(
        "--tp",
        metavar="TP_ID",
        required=True,
        help="identificador del TP (dobla como nombre de rama)",
    )
    parser.add_argument(
        "--cuatri",
        metavar="YYYY_N",
        default=CUATRIMESTRE,
        help="cuatrimestre para el que buscar entregas en el repo",
    )
    parser.add_argument(
        "--entregas-repo",
        metavar="PATH",
        default=ENTREGAS_REPO,
        help="ruta a un checkout de algoritmos-rw/algo2_entregas",
    )
    parser.add_argument("--pull-entregas", action="store_true")
    return parser.parse_args()


# TODO: DEFINITELY do not hardcode these
USERNAMES = {
    "103457": "tomascosta3",
    "103740": "milognr",
    "104302": "angysaavedra",
    "105147": "juancebarberis",
    "105296": "nazaquintero",
}


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


def update_repo(branch, subdir, upstream):
    """Actualiza un subdirectorio con archivos de otro repo.

    La función examina los commits en el upstream, y aplica los faltantes
    en la rama destina.

    TODO: Explicar (y mejorar) cómo se detecta qué falta.

    Args:
      branch (git.Branch): la rama donde aplicar las actualizaciones
      subdir (str): el subdirectorio particular a sincronizar con upstream
      upstream (Path): ruta en repo externo con los archivos actualizados
    """
    repo = branch.repo
    newest_in_repo = branch.commit.authored_date
    pending_commits = []

    upstream_repo = git.Repo(upstream, search_parent_directories=True)
    upstream_relpath = upstream.relative_to(upstream_repo.working_dir).as_posix()

    print(f"Processing {repo.working_dir}...", end=" ")

    for commit in upstream_repo.iter_commits(paths=[upstream_relpath]):
        if commit.authored_date > newest_in_repo:  # XXX Not robust enough.
            pending_commits.append(commit)

    if not pending_commits:
        print(f"nothing to do")
        return

    index = repo.index
    legajo = os.path.basename(repo.working_dir)  # XXX Drop this
    print(f"applying {len(pending_commits)} commit(s)")

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
        entrega_tree = commit.tree.join(upstream_relpath)
        updated_tree = overwrite_files(repo, entrega_tree, subdir)

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
        repo.index.reset(working_tree=True)


def get_branch(repo, branch_name):
    """Dado un repo, devolver la rama con ese nombre.
    """
    for branch in repo.branches:
        if branch.name == branch_name:
            return branch


def main():
    """Función principal del script (no invocada si se importa como módulo).
    """
    args = parse_args()
    entregas_base = pathlib.Path(args.entregas_repo) / args.tp / args.cuatri

    try:
        tprepo = git.Repo(args.entregas_repo)
    except git.exc.InvalidGitRepositoryError as ex:
        print(f"could not open entregas_repo at {repodir!r}: {ex}", file=sys.stderr)
        return 1

    if args.pull_entregas:
        print(f"Pulling from {args.entregas_repo}")
        remote = tprepo.remote()
        remote.pull()

    for repo in args.repos:
        legajo = os.path.basename(repo)  # XXX: Drop this
        try:
            repo = git.Repo(repo)
        except git.exc.InvalidGitRepositoryError as ex:
            print(f"could not open {repo!r}: {ex}", file=sys.stderr)
        else:
            # TODO: opportunistically return pull request URL.
            update_repo(get_branch(repo, args.tp), args.tp, entregas_base / legajo)


if __name__ == "__main__":
    sys.exit(main())

# Local Variables:
# eval: (blacken-mode 1)
# End:
