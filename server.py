import subprocess
from pathlib import Path
from urllib.parse import urlparse
import json
import shutil
import subprocess

from fastmcp import FastMCP

mcp = FastMCP("graphify")

REPOS_DIR = Path("/data/repos")
GRAPHS_DIR = Path("/data/graphs")


def find_graph_json(project_name: str) -> Path | None:
    """Find the Graphify graph.json belonging to a project with better search."""
    if not project_name or Path(project_name).name != project_name:
        raise ValueError("Invalid project name.")

    project_graph_dir = (GRAPHS_DIR / project_name).resolve()
    if not project_graph_dir.is_relative_to(GRAPHS_DIR.resolve()):
        raise ValueError("Project graph path is outside GRAPHS_DIR.")

    if not project_graph_dir.is_dir():
        return None

    # Multiple search strategies
    candidates = []
    
    # Strategy 1: Direct graph.json in project dir
    direct = project_graph_dir / "graph.json"
    if direct.is_file():
        candidates.append(direct)
    
    # Strategy 2: Recursive search for graph.json files
    for graph_file in project_graph_dir.rglob("graph.json"):
        if graph_file.is_file():
            candidates.append(graph_file)
    
    # Strategy 3: Look for graphify-out directory
    graphify_out = project_graph_dir / "graphify-out" / "graph.json"
    if graphify_out.is_file():
        candidates.append(graphify_out)
    
    # Strategy 4: Check for any JSON file that looks like a graph
    if not candidates:
        for json_file in project_graph_dir.rglob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    if 'nodes' in data or 'edges' in data or 'graph' in data:
                        candidates.append(json_file)
            except:
                continue
    
    # Sort by depth (prefer shallow paths) and name
    candidates.sort(key=lambda p: (len(p.parts), str(p)))
    return candidates[0].resolve() if candidates else None

def run_command(args: list[str], cwd: Path | None = None):
    """Run a command without a shell and capture diagnostics."""
    result = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False  # Don't raise immediately, handle errors manually
    )
    return result

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
        # Clone or update repository
        if not repo_path.exists():
            result = run_command([
                "git", "clone", "--depth", "1",
                "-b", branch, repo_url, str(repo_path),
            ])
            if result.returncode != 0:
                return f"Error cloning repository: {result.stderr}"
        else:
            if not (repo_path / ".git").exists():
                return (
                    f"Error: {repo_path} exists but is not a Git repository. "
                    "Move/rename it or choose a different project directory."
                )

            result = run_command(["git", "fetch", "origin"], cwd=repo_path)
            if result.returncode != 0:
                return f"Error fetching: {result.stderr}"
            
            result = run_command(["git", "checkout", branch], cwd=repo_path)
            if result.returncode != 0:
                return f"Error checkout: {result.stderr}"
            
            result = run_command(
                ["git", "pull", "--ff-only", "origin", branch],
                cwd=repo_path,
            )
            if result.returncode != 0:
                return f"Error pulling: {result.stderr}"

        # Clean previous graph output
        if graph_dir.exists():
            shutil.rmtree(graph_dir)
        graph_dir.mkdir(parents=True, exist_ok=True)

        # Try different Graphify scan commands
        scan_commands = [
            # Try with output as directory
            ["graphify", "scan", str(repo_path), "--output", str(graph_dir)],
            # Try with output as file
            ["graphify", "scan", str(repo_path), "--output", str(graph_dir / "graph.json")],
            # Try with different flag names
            ["graphify", "scan", str(repo_path), "-o", str(graph_dir)],
            ["graphify", "scan", str(repo_path), "--output-dir", str(graph_dir)],
        ]

        scan_success = False
        last_error = ""
        
        for cmd in scan_commands:
            result = run_command(cmd)
            if result.returncode == 0:
                scan_success = True
                break
            else:
                last_error = result.stderr or result.stdout

        if not scan_success:
            return (
                f"Graphify scan failed. Last error: {last_error}\n"
                f"Tried commands: {scan_commands}\n"
                "Please check Graphify installation and syntax."
            )

        # Verify graph was created
        graph_path = find_graph_json(repo_name)
        if graph_path is None:
            # List what was actually created
            created_files = []
            if graph_dir.exists():
                for f in graph_dir.rglob("*"):
                    if f.is_file():
                        created_files.append(str(f))
            
            return (
                "Scan command completed, but graph.json was not found.\n"
                f"Project output directory: {graph_dir}\n"
                f"Files created: {created_files if created_files else 'None'}\n"
                "Please check Graphify output format."
            )

        return (
            f"Success: repository '{repo_name}' scanned.\n"
            f"Repository: {repo_path}\n"
            f"Graph JSON: {graph_path}"
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
            # Debug: show what's in the graphs directory
            debug_info = []
            project_dir = GRAPHS_DIR / project_name
            if project_dir.exists():
                for f in project_dir.rglob("*"):
                    debug_info.append(str(f))
            
            return (
                f"Error: graph.json for project '{project_name}' was not found.\n"
                f"Project directory contents: {debug_info if debug_info else 'Empty'}\n"
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

        # Try different query command formats
        query_commands = [
            ["graphify", "query", question, "--graph", str(graph_path)],
            ["graphify", "query", "--graph", str(graph_path), question],
            ["graphify", "query", question, "-g", str(graph_path)],
        ]

        result = None
        last_error = ""
        
        for cmd in query_commands:
            result = run_command(cmd)
            if result.returncode == 0:
                break
            else:
                last_error = result.stderr or result.stdout

        if result is None or result.returncode != 0:
            return (
                f"Graphify query failed. Error: {last_error}\n"
                f"Graph file exists at: {graph_path}"
            )

        output = result.stdout.strip()
        if not output:
            output = "(Graphify returned no standard output.)"

        return (
            f"Project: {project_name}\n"
            f"Graph: {graph_path}\n\n"
            f"{output}"
        )

    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}"


@mcp.tool()
def list_projects() -> str:
    """List all projects that have been scanned."""
    if not GRAPHS_DIR.exists():
        return "No projects have been scanned yet."
    
    projects = []
    for project_dir in GRAPHS_DIR.iterdir():
        if project_dir.is_dir():
            graph = find_graph_json(project_dir.name)
            if graph:
                projects.append(f"- {project_dir.name}: {graph}")
            else:
                projects.append(f"- {project_dir.name}: (no graph.json found)")
    
    return "\n".join(projects) if projects else "No projects with valid graphs found."


if __name__ == "__main__":
    mcp.run(
        transport="sse", 
        host="0.0.0.0", 
        port=8000
    )
