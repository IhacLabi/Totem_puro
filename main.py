#! C:/Program Files/Python313/python.exe
# PORT = 8080

import os
import json
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
from datetime import datetime

# =========================
# CONFIGURAÇÕES
# =========================
PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(BASE_DIR, "Templates")
IMAGENS = os.path.join(BASE_DIR, "Imagens")

API_BASE = "https://www.ihaclabi.ufba.br/api.php/records"

# Sessão simples em memória
SESSAO = {
    "usuario": None,
    "id_user": None,
    "projetos": [],
    "json_filtro": []
}

# =========================
# FUNÇÕES DE INTEGRAÇÃO
# =========================
def carregar_usuarios():
    url = f"{API_BASE}/vwAlocacoes"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())
    return data.get("records", [])

def obter_projetos(id_user):
    url = f"{API_BASE}/vwAlocacoes?filter=usuário_idUsuario,eq,{id_user}"
    with urllib.request.urlopen(url) as resp:
        data = json.loads(resp.read().decode())
    projetos = list(set(r['descProjeto'] for r in data.get("records", [])))
    return projetos, data.get("records", [])

def registrar_acesso(id_alocacao):
    payload = json.dumps({
        "UsuarioXProjetoXRecurso_idUsuarioXProjetoXRecurso": id_alocacao
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/acessos",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def sincronizar_usuario_e_projetos(rfid):
    registros = carregar_usuarios()
    usuario_api = next((u for u in registros if u["NFCId"] == rfid), None)
    if not usuario_api:
        return None, None, None
    projetos_api, alocacoes_api = obter_projetos(usuario_api["usuário_idUsuario"])
    return usuario_api, projetos_api, alocacoes_api

# =========================
# HANDLER HTTP
# =========================
class MeuHandler(BaseHTTPRequestHandler):

    def _responder_html(self, filename, status=200, context=None):
        """Carrega um HTML estático ou insere dados dinamicamente"""
        try:
            filepath = os.path.join(TEMPLATES, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                html = f.read()

            # Substituir variáveis {{chave}} se contexto for fornecido
            if context:
                for chave, valor in context.items():
                    html = html.replace(f"{{{{{chave}}}}}", str(valor))

            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        except FileNotFoundError:
            self.send_error(404, f"Arquivo não encontrado: {filename}")

    def _responder_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_GET(self): # Rever as imagens
        # Servindo imagens estáticas
        if self.path.startswith("/Imagens/"):
            filepath = os.path.join(IMAGENS, os.path.basename(self.path))
            if os.path.exists(filepath):
                self.send_response(200)
                if filepath.endswith(".png"):
                    self.send_header("Content-Type", "image/png")
                elif filepath.endswith(".jpg") or filepath.endswith(".jpeg"):
                    self.send_header("Content-Type", "image/jpeg")
                else:
                    self.send_header("Content-Type", "application/octet-stream")
                self.end_headers()
                with open(filepath, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "Imagem não encontrada")
            return

        # Rotas principais
        if self.path == "/":
            self._responder_html("Singup.html")
        elif self.path == "/selecionar_projeto":
            if SESSAO["usuario"]:
                # Monta lista dinâmica de projetos
                projetos_html = "".join(
                    f"<option value='{p}'>{p}</option>" for p in SESSAO["projetos"]
                )
                context = {"usuario": SESSAO['usuario']["nomeUsuario"], "lista_projetos": projetos_html}
                self._responder_html("Ponto.html", context=context)
            else:
                self._responder_html("Singup.html")
        else:
            self.send_error(404, "Rota não encontrada")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")

        if self.path == "/":
            # RFID vindo do formulário
            data = parse_qs(body)
            rfid = data.get("rfid", [None])[0]
            usuario_api, projetos, json_filtro = sincronizar_usuario_e_projetos(rfid)

            if usuario_api:
                SESSAO["usuario"] = usuario_api
                SESSAO["id_user"] = usuario_api["usuário_idUsuario"]
                SESSAO["projetos"] = projetos
                SESSAO["json_filtro"] = json_filtro
                self.send_response(302)
                self.send_header("Location", "/selecionar_projeto")
                self.end_headers()
            else:
                self._responder_html("Singup.html", context={"erro": "Cartão RFID não reconhecido"})

        elif self.path == "/selecionar_projeto":
            data = parse_qs(body)
            projeto_selecionado = data.get("projeto", [None])[0]
            id_alocacao = data.get("id_alocacao", [None])[0]

            if projeto_selecionado:
                recursos = [r for r in SESSAO["json_filtro"] if r["descProjeto"] == projeto_selecionado]
                self._responder_json({"projeto": projeto_selecionado, "recursos": recursos})
            elif id_alocacao:
                registrar_acesso(int(id_alocacao))
                SESSAO.clear()
                self._responder_html("Singup.html", context={"msg": "Acesso registrado com sucesso!"})
            else:
                self._responder_html("Ponto.html", context={"erro": "Nenhum dado enviado"})

        elif self.path == "/api/processar_rfid":
            data = json.loads(body)
            rfid = data.get("rfid")
            usuario_api, projetos, alocacoes = sincronizar_usuario_e_projetos(rfid)

            if not usuario_api:
                self._responder_json({"error": "RFID não reconhecido"}, 404)
                return

            SESSAO["usuario"] = usuario_api
            SESSAO["id_user"] = usuario_api["usuário_idUsuario"]
            SESSAO["projetos"] = projetos
            SESSAO["json_filtro"] = alocacoes

            resp = {"status": "ok", "usuario": usuario_api, "projetos": projetos}
            self._responder_json(resp)

        elif self.path == "/api/registrar_acesso":
            data = json.loads(body)
            id_alocacao = data.get("id_alocacao")
            if not id_alocacao:
                self._responder_json({"error": "id_alocacao não fornecido"}, 400)
                return

            registrar_acesso(int(id_alocacao))
            resp = {
                "status": "ok",
                "acesso": {
                    "id_alocacao": id_alocacao,
                    "data_hora": datetime.utcnow().isoformat(),
                    "sucesso": True
                }
            }
            self._responder_json(resp)
        else:
            self.send_error(404, "Rota não encontrada")

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), MeuHandler)
    print(f"Servidor rodando em http://127.0.0.1:{PORT}")
    server.serve_forever()


