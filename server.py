import os
import subprocess
import shutil
import glob
import zipfile
import io
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
    """Menghapus seluruh folder project tepat di bawah GRAPHS_DIR dan REPOS_DIR 
    berdasarkan nama folder yang dipilih dari list_projects."""
    
    clean_project_name = os.path.basename(os.path.normpath(project_name))

    if not clean_project_name or clean_project_name in [".", ".."]:
        return "Error: Nama project tidak valid."

    graph_folder_path = os.path.join(GRAPHS_DIR, clean_project_name)
    repo_folder_path = os.path.join(REPOS_DIR, clean_project_name)

    deleted_items = []

    if os.path.exists(graph_folder_path) and os.path.isdir(graph_folder_path):
        shutil.rmtree(graph_folder_path)
        deleted_items.append("folder data graph")

    if os.path.exists(repo_folder_path) and os.path.isdir(repo_folder_path):
        shutil.rmtree(repo_folder_path)
        deleted_items.append("source code repo")

    if not deleted_items:
        return f"Project folder '{clean_project_name}' tidak ditemukan di sistem."

    return f"Sukses! Project '{clean_project_name}' berhasil dihapus sepenuhnya ({', '.join(deleted_items)})."
    

@mcp.tool()
def upload_and_scan_zip(project_name: str, zip_bytes: bytes) -> str:
    """Menerima upload manual file ZIP project"""
    
    project_name = os.path.basename(os.path.normpath(project_name))
    
    if not project_name or project_name in [".", ".."]:
        return "Error: Nama project tidak valid."

    repo_path = os.path.join(REPOS_DIR, project_name)
    graph_output = os.path.join(GRAPHS_DIR, project_name)

    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)
    if os.path.exists(graph_output):
        shutil.rmtree(graph_output)
        
    os.makedirs(repo_path, exist_ok=True)
    os.makedirs(graph_output, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_ref:
            zip_ref.extractall(repo_path)
    except zipfile.BadZipFile:
        return "Error: File yang dikirimkan rusak atau bukan format ZIP yang valid."
    except Exception as e:
        return f"Gagal mengekstrak file ZIP: {str(e)}"

    scan_cmd = f"graphify {repo_path} --output {graph_output}/graph.json"
    scan_process = subprocess.run(scan_cmd, shell=True, capture_output=True, text=True)

    html_cmd = f"graphify export html --graph {graph_output}/graph.json"
    subprocess.run(html_cmd, shell=True)

    if scan_process.returncode != 0:
        return f"ZIP berhasil diekstrak, tetapi proses scan Graphify gagal.\n\nLog Error:\n{scan_process.stderr}"

    return f"Sukses! Project ZIP '{project_name}' berhasil diekstrak dan dianalisa. Struktur folder terdeteksi dan file graph tersimpan di database."


if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
