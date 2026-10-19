import subprocess
from pathlib import Path
from urllib.parse import urlparse

from fastmcp import FastMCP

mcp = FastMCP("graphify")

REPOS_DIR = Path("/data/repos")
GRAPHS_DIR = Path("/data/graphs")


def find_graph_json(project_name: str) -> Path | None:
    """Find the Graphify graph.json belonging to a project."""
    if not project_name or Path(project_name).name != project_name:
        raise ValueError("Invalid project name.")

    project_graph_dir = (GRAPHS_DIR / project_name).resolve()
    if not project_graph_dir.is_relative_to(GRAPHS_DIR.resolve()):
        raise ValueError("Project graph path is outside GRAPHS_DIR.")

    if not project_graph_dir.is_dir():
        return None

    # Search nested output directories because Graphify output layout
    # can differ by CLI version/configuration.
    candidates = sorted(
        (
            p for p in project_graph_dir.rglob("graph.json")
            if p.is_file()
        ),
        key=lambda p: (len(p.parts), str(p)),
    )
    return candidates[0].resolve() if candidates else None


def run_command(args: list[str], cwd: Path | None = None):
    """Run a command without a shell and capture diagnostics."""
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=True,
    )


@mcp.tool()
def sync_and_scan_repository(repo_url: str, branch: str = "main") -> str:
    """Clone/pull a GitHub repository and scan it with Graphify."""
    parsed = urlparse(repo_url.strip())

    if parsed.scheme != "https" or parsed.hostname != "github.com":
        return "Error: repo_url must be an HTTPS URL on github.com."

    repo_name = Path(parsed.path.rstrip("/")).stem
    if not repo_name or repo_name in {".", ".."}:
        return "Error: Could not determine a valid repository name."

    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    GRAPHS_DIR.mkdir(parents=True, exist_ok=True)

    repo_path = (REPOS_DIR / repo_name).resolve()
    graph_dir = (GRAPHS_DIR / repo_name).resolve()

    if not repo_path.is_relative_to(REPOS_DIR.resolve()):
        return "Error: Repository path is outside REPOS_DIR."
    if not graph_dir.is_relative_to(GRAPHS_DIR.resolve()):
        return "Error: Graph path is outside GRAPHS_DIR."

    try:
        if not repo_path.exists():
            run_command([
                "git", "clone", "--depth", "1",
                "-b", branch, repo_url, str(repo_path),
            ])
        else:
            if not (repo_path / ".git").exists():
                return (
                    f"Error: {repo_path} exists but is not a Git repository. "
                    "Move/rename it or choose a different project directory."
                )

            run_command(["git", "fetch", "origin"], cwd=repo_path)
            run_command(["git", "checkout", branch], cwd=repo_path)
            run_command(
                ["git", "pull", "--ff-only", "origin", branch],
                cwd=repo_path,
            )

        graph_dir.mkdir(parents=True, exist_ok=True)

        # NOTE: Verify `graphify scan --help` for your installed Graphify
        # version. If --output expects a file rather than a directory,
        # adjust this command to that version's documented syntax.
        run_command([
            "graphify", "scan", str(repo_path),
            "--output", str(graph_dir),
        ])

        graph_path = find_graph_json(repo_name)
        if graph_path is None:
            return (
                "Scan command completed, but graph.json was not found.\n"
                f"Project output directory: {graph_dir}\n"
                "Inspect the Graphify output and run `graphify scan --help` "
                "to confirm the supported --output syntax."
            )

        return (
            f"Success: repository '{repo_name}' scanned.\n"
            f"Repository: {repo_path}\n"
            f"Graph JSON: {graph_path}"
        )

    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        return (
            f"Command failed (exit code {exc.returncode}): {exc.cmd}\n"
            f"{detail}"
        )
    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}"


@mcp.tool()
def query_project_graph(
    project_name: str,
    query_type: str,
    target_symbol: str,
) -> str:
    """Query the graph.json belonging to a previously scanned project."""
    if not project_name or Path(project_name).name != project_name:
        return "Error: Invalid project_name."

    if not target_symbol or not target_symbol.strip():
        return "Error: target_symbol/query is required."

    try:
        graph_path = find_graph_json(project_name)
        if graph_path is None:
            return (
                f"Error: graph.json for project '{project_name}' was not found. "
                "Run sync_and_scan_repository first."
            )

        mode = (query_type or "query").strip().lower()
        prompts = {
            "dependencies": (
                f"Explain the dependencies and relationships of {target_symbol}."
            ),
            "function": (
                f"Explain the function, implementation, and callers of "
                f"{target_symbol}."
            ),
            "architecture": (
                f"Explain the architecture and connections related to "
                f"{target_symbol}."
            ),
            "query": target_symbol,
        }

        question = prompts.get(mode)
        if question is None:
            return (
                "Error: query_type must be one of: dependencies, function, "
                "architecture, query."
            )

        # Confirm the exact query syntax with `graphify query --help`
        # for the installed Graphify version.
        result = run_command([
            "graphify", "query", question,
            "--graph", str(graph_path),
        ])

        output = result.stdout.strip()
        if not output:
            output = "(Graphify returned no standard output.)"

        return (
            f"Project: {project_name}\n"
            f"Graph: {graph_path}\n\n"
            f"{output}"
        )

    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        return (
            f"Graphify query failed (exit code {exc.returncode}).\n"
            f"{detail}"
        )
    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}"


if __name__ == "__main__":
        mcp.run(
        transport="sse", 
        host="0.0.0.0", 
        port=8000
    )
