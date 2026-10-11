import os
import subprocess
import shutil
import glob
from urllib.parse import urlparse
from fastmcp import FastMCP

mcp = FastMCP("Graphify Hub")

REPOS_DIR = "/data/repos"
GRAPHS_DIR = "/data/graphs"

@mcp.tool()
def sync_and_scan_repository(repo_url: str, branch: str = "main") -> str:
    """Clone atau pull repo GitHub terbaru, lalu jalankan analisa Graphify."""
    repo_name = os.path.splitext(os.path.basename(urlparse(repo_url).path))[0]
    repo_path = os.path.join(REPOS_DIR, repo_name)
    graph_output = os.path.join(GRAPHS_DIR, f"{repo_name}.json")

    # 1. Git Clone atau Pull
    if not os.path.exists(repo_path):
        clone_cmd = f"git clone --depth 1 -b {branch} {repo_url} {repo_path}"
        subprocess.run(clone_cmd, shell=True, check=True)
    else:
        pull_cmd = f"cd {repo_path} && git fetch && git checkout {branch} && git pull"
        subprocess.run(pull_cmd, shell=True, check=True)

    # 2. Graphify Scan
    scan_cmd = f"graphify {repo_path} --output {graph_output}"
    scan_process = subprocess.run(scan_cmd, shell=True, capture_output=True, text=True)

    html_cmd = f"graphify export html --graph {graph_output}/graphify-out/graph.json"
    html_process = subprocess.run(html_cmd, shell=True)

    if scan_process.returncode != 0:
        return f"Git pull berhasil, tapi proses scan gagal.\n\nPesan Error Asli:\n{scan_process.stderr}\n\nLog Output:\n{scan_process.stdout}"

    return f"Sukses! Repositori '{repo_name}' berhasil disinkronkan dan dianalisa. File graph tersimpan di {graph_output}."

@mcp.tool()
def query_project_graph(project_name: str, query_type: str, target_symbol: str) -> str:
    """Membaca dependensi, fungsi, atau arsitektur dari repositori yang sudah di-scan."""
    graph_path = os.path.join(GRAPHS_DIR, f"{project_name}.json")
    if not os.path.exists(graph_path):
        return f"Error: Project '{project_name}' belum pernah di-scan. Jalankan sync_and_scan_repository dulu."

    query_cmd = f"graphify query {graph_path} --type {query_type} --symbol {target_symbol}"
    res = subprocess.run(query_cmd, shell=True, capture_output=True, text=True)
    return res.stdout if res.returncode == 0 else f"Error: {res.stderr}"

if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8000)

@mcp.tool()
def list_projects() -> str:
    """Melihat daftar seluruh nama project"""
    if not os.path.exists(GRAPHS_DIR):
        return "Belum ada project yang tersimpan."
    
    project_list = []
    try:
        with os.scandir(GRAPHS_DIR) as entries:
            for entry in entries:
                if entry.is_dir():
                    project_name = entry.name
                    project_list.append(f"- {project_name}")
    except OSError as e:
        return f"Gagal membaca direktori graph: {str(e)}"
        
    if not project_list:
        return "Belum ada project yang tersimpan."
    
    project_list.sort()
    
    return "Project yang tersedia:\n" + "\n".join(project_list)


@mcp.tool()
def delete_project(project_name: str) -> str:
    """Menghapus data project"""
    
    project_name = os.path.normpath(project_name)
    
    graph_path = os.path.join(GRAPHS_DIR, f"{project_name}.json")
    repo_path = os.path.join(REPOS_DIR, project_name)

    deleted_items = []

    parts = project_name.split(os.sep)
    
    if len(parts) > 1:
        target_root_folder = os.path.join(GRAPHS_DIR, parts[0])
        
        if os.path.exists(target_root_folder) and os.path.isdir(target_root_folder):
            shutil.rmtree(target_root_folder)
            deleted_items.append(f"folder graph '{parts[0]}' secara recursive")
    else:
        if os.path.exists(graph_path):
            os.remove(graph_path)
            deleted_items.append("file graph")
            
    repo_root_part = parts[0]
    target_repo_path = os.path.join(REPOS_DIR, repo_root_part)
    
    if os.path.exists(target_repo_path):
        shutil.rmtree(target_repo_path)
        deleted_items.append("source code repo")

    if not deleted_items:
        return f"Project '{project_name}' tidak ditemukan di sistem."

    return f"Project '{project_name}' berhasil dihapus ({', '.join(deleted_items)})."
