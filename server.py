import os
import subprocess
import shutil
import json
import base64
import zipfile
import io
from urllib.parse import urlparse
from typing import Optional, Dict, Any
from fastmcp import FastMCP

mcp = FastMCP("Graphify Hub")

REPOS_DIR = "/data/repos"
GRAPHS_DIR = "/data/graphs"

os.makedirs(REPOS_DIR, exist_ok=True)
os.makedirs(GRAPHS_DIR, exist_ok=True)


def _resolve_graph_file(project_name: str) -> Optional[str]:
    """Helper untuk menemukan letak file graph.json yang valid."""
    clean_name = os.path.basename(os.path.normpath(project_name))
    
    # 1. Format direktori: /data/graphs/<name>/graph.json
    p1 = os.path.join(GRAPHS_DIR, clean_name, "graph.json")
    if os.path.isfile(p1):
        return p1
        
    # 2. Format file langsung: /data/graphs/<name>.json
    p2 = os.path.join(GRAPHS_DIR, f"{clean_name}.json")
    if os.path.isfile(p2):
        return p2
        
    # 3. Format subfolder: /data/graphs/<name>/graphify-out/graph.json
    p3 = os.path.join(GRAPHS_DIR, clean_name, "graphify-out", "graph.json")
    if os.path.isfile(p3):
        return p3
        
    return None


@mcp.tool()
def list_projects() -> str:
    """Melihat daftar seluruh nama project yang sudah tersedia di sistem."""
    if not os.path.exists(GRAPHS_DIR):
        return "Belum ada project yang tersimpan."
    
    projects = set()
    try:
        with os.scandir(GRAPHS_DIR) as entries:
            for entry in entries:
                if entry.is_dir():
                    projects.add(entry.name)
                elif entry.is_file() and entry.name.endswith(".json"):
                    projects.add(entry.name[:-5])
    except OSError as e:
        return f"Gagal membaca direktori graph: {str(e)}"
        
    if not projects:
        return "Belum ada project yang tersimpan."
    
    return "Project yang tersedia:\n" + "\n".join([f"- {p}" for p in sorted(list(projects))])


@mcp.tool()
def sync_and_scan_repository(repo_url: str, branch: str = "main") -> str:
    """Clone atau pull repo GitHub terbaru, lalu buat file graph.json."""
    repo_name = os.path.splitext(os.path.basename(urlparse(repo_url).path))[0]
    repo_path = os.path.join(REPOS_DIR, repo_name)
    graph_project_dir = os.path.join(GRAPHS_DIR, repo_name)
    graph_output_file = os.path.join(graph_project_dir, "graph.json")

    os.makedirs(graph_project_dir, exist_ok=True)

    if not os.path.exists(repo_path):
        clone_cmd = f"git clone --depth 1 -b {branch} {repo_url} {repo_path}"
        res = subprocess.run(clone_cmd, shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            return f"Git clone gagal:\n{res.stderr}"
    else:
        pull_cmd = f"cd {repo_path} && git fetch && git checkout {branch} && git pull"
        res = subprocess.run(pull_cmd, shell=True, capture_output=True, text=True)
        if res.returncode != 0:
            return f"Git pull gagal:\n{res.stderr}"

    scan_cmd = f"graphify {repo_path} --output {graph_output_file}"
    scan_process = subprocess.run(scan_cmd, shell=True, capture_output=True, text=True)

    if scan_process.returncode != 0:
        return f"Scan Graphify gagal.\nError:\n{scan_process.stderr}\nOutput:\n{scan_process.stdout}"

    html_cmd = f"graphify export html --graph {graph_output_file}"
    subprocess.run(html_cmd, shell=True, capture_output=True)

    return f"Sukses! Project '{repo_name}' berhasil disinkronkan dan dianalisa. Graph tersimpan."


@mcp.tool()
def upload_and_scan_zip(project_name: str, zip_base64: str) -> str:
    """Menerima upload base64 file ZIP project, ekstrak ke repo dir, lalu jalankan analisa."""
    project_name = os.path.basename(os.path.normpath(project_name))
    if not project_name or project_name in [".", ".."]:
        return "Error: Nama project tidak valid."

    repo_path = os.path.join(REPOS_DIR, project_name)
    graph_project_dir = os.path.join(GRAPHS_DIR, project_name)
    graph_output_file = os.path.join(graph_project_dir, "graph.json")

    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)
    if os.path.exists(graph_project_dir):
        shutil.rmtree(graph_project_dir)
        
    os.makedirs(repo_path, exist_ok=True)
    os.makedirs(graph_project_dir, exist_ok=True)

    try:
        zip_data = base64.b64decode(zip_base64)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zip_ref:
            zip_ref.extractall(repo_path)
    except zipfile.BadZipFile:
        return "Error: File yang dikirimkan rusak atau bukan file ZIP yang valid."
    except Exception as e:
        return f"Gagal mengekstrak file ZIP: {str(e)}"

    scan_cmd = f"graphify {repo_path} --output {graph_output_file}"
    scan_process = subprocess.run(scan_cmd, shell=True, capture_output=True, text=True)

    if scan_process.returncode != 0:
        return f"ZIP berhasil diekstrak, tetapi proses scan Graphify gagal:\n{scan_process.stderr}"

    html_cmd = f"graphify export html --graph {graph_output_file}"
    subprocess.run(html_cmd, shell=True, capture_output=True)

    return f"Sukses! Project '{project_name}' diekstrak dan dianalisa. Graph tersimpan."


@mcp.tool()
def get_project_summary(project_name: str) -> str:
    """Membaca isi graph.json langsung untuk melihat ikhtisar struktur project tanpa scan ulang."""
    graph_path = _resolve_graph_file(project_name)
    if not graph_path:
        return f"Error: Graph untuk project '{project_name}' tidak ditemukan."

    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        nodes = data.get("nodes", [])
        edges = data.get("edges", [])

        node_types: Dict[str, int] = {}
        sample_nodes = []
        for n in nodes:
            t = n.get("type", "unknown")
            node_types[t] = node_types.get(t, 0) + 1
            if len(sample_nodes) < 20:
                name = n.get("label") or n.get("id") or n.get("name")
                sample_nodes.append(f"{name} ({t})")

        return (
            f"=== Overview Project: {project_name} ===\n"
            f"Total Komponen/Simbol: {len(nodes)}\n"
            f"Total Relasi: {len(edges)}\n"
            f"Tipe Node: {json.dumps(node_types, indent=2)}\n"
            f"Contoh Node Terdeteksi:\n" + "\n".join([f"- {s}" for s in sample_nodes])
        )
    except Exception as e:
        return f"Gagal membaca file graph.json: {str(e)}"


@mcp.tool()
def read_project_file(project_name: str, relative_file_path: str) -> str:
    """Membaca isi file source code langsung dari project yang ada di container (misal: index.php, config.php)."""
    clean_project = os.path.basename(os.path.normpath(project_name))
    repo_path = os.path.join(REPOS_DIR, clean_project)
    
    target_path = os.path.normpath(os.path.join(repo_path, relative_file_path))
    
    # Keamanan: cegah traversal di luar folder repositori
    if not target_path.startswith(repo_path):
        return "Error: Akses path di luar direktori project ditolak."
        
    if not os.path.exists(target_path):
        return f"File '{relative_file_path}' tidak ditemukan di repositori project '{clean_project}'."
        
    if os.path.isdir(target_path):
        files = os.listdir(target_path)
        return f"Path adalah direktori. Berisi: {', '.join(files)}"

    try:
        with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        return f"Gagal membaca file: {str(e)}"


@mcp.tool()
def query_project_graph(project_name: str, query_type: str, target_symbol: str) -> str:
    """Menjalankan Graphify query pada file graph.json yang ada."""
    graph_path = _resolve_graph_file(project_name)
    if not graph_path:
        return f"Error: Project '{project_name}' belum pernah di-scan atau graph tidak ditemukan."

    query_cmd = f"graphify query {graph_path} --type {query_type} --symbol {target_symbol}"
    res = subprocess.run(query_cmd, shell=True, capture_output=True, text=True)
    return res.stdout if res.returncode == 0 else f"Error: {res.stderr}"


@mcp.tool()
def delete_project(project_name: str) -> str:
    """Menghapus project dari REPOS_DIR dan GRAPHS_DIR."""
    clean_name = os.path.basename(os.path.normpath(project_name))
    if not clean_name or clean_name in [".", ".."]:
        return "Error: Nama project tidak valid."

    deleted = []
    g_dir = os.path.join(GRAPHS_DIR, clean_name)
    g_file = os.path.join(GRAPHS_DIR, f"{clean_name}.json")
    r_dir = os.path.join(REPOS_DIR, clean_name)

    if os.path.isdir(g_dir):
        shutil.rmtree(g_dir)
        deleted.append("graph dir")
    if os.path.isfile(g_file):
        os.remove(g_file)
        deleted.append("graph file")
    if os.path.isdir(r_dir):
        shutil.rmtree(r_dir)
        deleted.append("source repo")

    if not deleted:
        return f"Project '{clean_name}' tidak ditemukan."

    return f"Sukses menghapus: {', '.join(deleted)}"


if __name__ == "__main__":
    mcp.run(transport="sse", host="0.0.0.0", port=8000)
