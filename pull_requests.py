#!/usr/bin/python3

"""Script/módulo para sincronizar las entregas con repositorios individuales.

Uso como script:

  $ ./pull_requests.py --tp <TP_ID> <legajo>...

donde TP_ID es el TP a sincronizar ("tp0", "vector", etc.). Se puede
especificar la ubicación del checkout de algoritmos-rw/algo2_entregas
con la opción --entregas-repo, y la ubicación de los repositorios
individuales con --alu-repodir. fiubatp.tsv debe estar presente en el
directorio actual, o especificarse con --planilla.

Uso como módulo: llamar a update_repo() indicando el TP, la ruta a la
entrega, y el directorio con los repositorios individuales.
"""

import argparse
import csv
import io
import os
import pathlib
import sys

import git  # apt install python3-git
import git.index.fun as indexfun
import git.objects.fun as objfun

from git.util import bin_to_hex, stream_copy
from git.objects import Blob
from git.index.typ import BaseIndexEntry
from gitdb.base import IStream


# Defaults si no se ajustan por la línea de comandos.
ENTREGAS_REPO = os.path.expanduser("~/fiuba/tprepo")
ALU_REPOS_DIR = os.path.expanduser("~/fiuba/alurepo")

# Default si no se especifica con --cuatri.
CUATRIMESTRE = "2020_1"


## Función principal para corrector.py
##
def update_repo(tp_id, repodir, upstream, planilla_tsv, silent=True):
    """Importa la última versión de una entrega a un repositorio individual.

    Args:
      tp_id (str): identificador del TP (dobla como subdirectorio y rama)
      repodir (Path): ruta al repositorio destino (se clona si no existe)
      upstream (Path): ruta en repo externo con los archivos actualizados
      planilla_file (str): hoja "fiubatp" de la planilla exportada en TSV
    """
    legajo = repodir.name  # Siempre cumplimos que `basename $REPO` == legajo.
    alu_dict = None

    # Buscar legajo en la "planilla".
    with open(planilla_tsv, newline="") as fileobj:
        for row in csv.DictReader(fileobj, dialect="excel-tab"):
            if row["Legajo"] == legajo:
                alu_dict = row
                break
        else:
            if not silent:
                # Demasiado spam si la planilla solo tiene los legajos habilitados.
                print(f"no se pudo encontrar legajo {legajo} en {planilla_tsv}")
            return

    # Sanity checks.
    if not alu_dict.get("Github"):
        print(f"no se pudo encontrar cuenta de Github para {legajo}")
        return
    elif not repodir.exists() and not alu_dict.get("Repo"):
        print(f"no se pudo encontrar repo URL para {legajo}")
        return

    if not repodir.exists():
        git.Repo.clone_from("git@github.com:" + alu_dict["Repo"], repodir)

    try:
        repo = git.Repo(repodir)
    except git.exc.InvalidGitRepositoryError as ex:
        print(f"could not open {repodir!r}: {ex}", file=sys.stderr)
    else:
        # TODO: opportunistically return pull request URL.
        branch = get_or_checkout_branch(repo, tp_id)
        update_branch(branch, tp_id, upstream, alu_dict["Github"])


def parse_args():
    """Parse command line options and arguments.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "legajos",
        metavar="legajo",
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
        "--planilla",
        metavar="TSV_FILE",
        default="fiubatp.tsv",
        help="archivo TSV con los contenidos de la hoja 'fiubatp'",
    )
    parser.add_argument(
        "--alu-repodir",
        metavar="PATH",
        default=ALU_REPOS_DIR,
        help="directorio con los repositorios individuales",
    )
    parser.add_argument(
        "--entregas-repo",
        metavar="PATH",
        default=ENTREGAS_REPO,
        help="ruta a un checkout de algoritmos-rw/algo2_entregas",
    )
    parser.add_argument("--pull-entregas", action="store_true")
    return parser.parse_args()


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


def update_branch(branch, subdir, upstream, ghuser):
    """Actualiza una rama con archivos de otro repo.

    La función examina los commits en el upstream, y aplica los faltantes
    en la rama destino.

    TODO: Explicar (y mejorar) cómo se detecta qué falta.

    Args:
      branch (git.Branch): la rama donde aplicar las actualizaciones
      subdir (str): el subdirectorio particular a sincronizar con upstream
      upstream (Path): ruta en repo externo con los archivos actualizados
      ghuser (str): nombre de cuenta de Github con que crear los commits.
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

    print(f"applying {len(pending_commits)} commit(s)")

    branch.checkout()
    author = git.Actor(ghuser, f"{ghuser}@users.noreply.github.com")

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


def get_or_checkout_branch(repo, branch_name):
    """Dado un repo, devolver la rama con ese nombre.

    Si la rama no existe, se crea a partir de una rama remota llamada igual
    o de la rama master local.
    """
    for args in [], ["-t", f"origin/{branch_name}"], ["-b", branch_name, "master"]:
        if args:
            try:
                repo.git.checkout(args)
            except git.exc.GitCommandError:
                pass
        for branch in repo.branches:
            if branch.name == branch_name:
                return branch


def main():
    """Función principal del script (no invocada si se importa como módulo).
    """
    args = parse_args()
    repodir = pathlib.Path(args.alu_repodir)
    entregas_repo = pathlib.Path(args.entregas_repo)

    try:
        tprepo = git.Repo(args.entregas_repo)
    except git.exc.InvalidGitRepositoryError as ex:
        print(f"could not open entregas_repo at {repodir!r}: {ex}", file=sys.stderr)
        return 1

    if args.pull_entregas:
        print(f"Pulling from {args.entregas_repo}")
        remote = tprepo.remote()
        remote.pull()

    for legajo in args.legajos:
        alurepo = repodir / legajo
        upstream = entregas_repo / args.tp / args.cuatri / legajo
        if upstream.exists():
            update_repo(args.tp, alurepo, upstream, args.planilla)
        else:
            print(
                f"no hay entrega para {upstream.relative_to(entregas_repo)}",
                file=sys.stderr,
            )


if __name__ == "__main__":
    sys.exit(main())

# Local Variables:
# eval: (blacken-mode 1)
# End:
