import collections
import os
import pathlib
import shutil
import subprocess
import sys

import jinja2

TEMPL_DIR = os.path.dirname(__file__)
ResultTuple = collections.namedtuple("ResultTuple", "succ, log")


class CorregirJava:
  """Compila y corrige una entrega.
  """
  def __init__(self, directory, timeout=None):
    self.path = pathlib.Path(directory)
    alu = self.path / "orig"
    pub = self.path / "skel"
    corr = self.path / "corr"
    corr.mkdir()

    for path in alu, pub:
      for file in path.glob("**/*.java"):
        shutil.copy(file, corr)

    shutil.copy(pub / "build.xml", self.path)

  def run(self):
    steps = ["compilar", "validar_api", "pruebas_basicas"]
    outcomes = {step: None for step in steps}
    final_result = {"steps": outcomes, "reject": False}

    try:
      for step in steps:
        silence = [] if step == "pruebas_basicas" else ["-q", "-S"]
        cmd = subprocess.run(["ant", step] + silence, cwd=self.path,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        success = (cmd.returncode == 0)
        outcomes[step] = ResultTuple(success,
                                     cmd.stdout.decode("utf-8", "replace"))
        if not success:
          final_result["reject"] = True
          break
    finally:
      jinja = jinja2.Environment(line_statement_prefix="#",
                                 line_comment_prefix="--",
                                 loader=jinja2.FileSystemLoader(TEMPL_DIR))
      templ = jinja.get_template("reply-java.j2")
      sys.stdout.write(templ.render(final_result))
      sys.stdout.flush()