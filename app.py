import streamlit as st
import requests
import os
from google.cloud import storage
import uuid
import io  # Importei o módulo io para trabalhar com BytesIO



def deletar_pastas(uuid_str):
  storage_client = storage.Client()
  bucket_name = "guardhouse_automation_bucket"
  bucket = storage_client.bucket(bucket_name)
  blobs = bucket.list_blobs(prefix=f"{uuid_str}/") #lista todos arquivos com prefixo
  for blob in blobs:
    blob.delete()
  print(f"Pasta com UUID {uuid_str} deletada.")

def download_excel_from_api(api_url, filename="output"):
    try:
        response = requests.get(api_url, stream=True) #stream=True para lidar com arquivos grandes
        response.raise_for_status()  # Lança uma exceção para erros HTTP

        st.download_button(
            label="Baixar Excel",
            data=response.content, #usa response.content ao inves de response.iter_content pois o streamlit precisa dos bytes
            file_name=f"{filename}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao baixar o arquivo: {e}")
    except Exception as e:
        st.error(f"Ocorreu um erro: {e}")

FASTAPI_URL = "http://127.0.0.1:8000"

st.title("GuardHouse Automation")

# Inicializa o UUID no session_state, se ainda não existir
if "uuid_str" not in st.session_state:
    st.session_state.uuid_str = str(uuid.uuid4())
    st.write("Novo UUID gerado:", st.session_state.uuid_str) #exibe o uuid gerado


st.write('''O GuardHouse Automation é um aplicativo de automação de guarita, 
         você enviar fotos de documentos e de carros e recebe um arquivo excel
         com nome, cpf, rg, placa, modelo do carro e fabricante.
         Tudo automaticamente sem necessidade de anotar ou digitar manualmente.
         Não precisa se preocupar com a ordem de envio dos arquivos.
         O aplicativo vai fazer a inferencia de qual documento é de qual motorista pelo horario 
         da foto. 
         Então é só tirar as fotos na sequência documento do condutor, foto do carro pegando a placa.
         Tem que ter a mesma quantidade de fotos de documentos e de carros.
         Não use fotos recebidas por WhatsApp ou qualquer aplicativo de mensageria, o aplicativo
         não tem como inferir a ordem das fotos de arquivos desses aplicativos por excluirem os 
         metadados para sua privacidade.
         Selecione as fotos e aperte em enviar.
         Em poucos segundos você receberá o arquivo com sua tabela.''')

# Campos de upload separados
documentos = st.file_uploader("Selecione os Documentos", accept_multiple_files=True, type=["jpg", "jpeg", "png"])
placas = st.file_uploader("Selecione as Placas", accept_multiple_files=True, type=["jpg", "jpeg", "png"])

if st.button("Enviar Imagens"):
    if documentos or placas:
        uuid_str = st.session_state.uuid_str
        for img_type in ["documentos", "placas"]:
            response = requests.post(f"{FASTAPI_URL}/upload", files=documentos, params={"uuid":uuid_str, "img_type":img_type})
            response.raise_for_status()

            # Verifica se a mensagem de sucesso está na resposta
            if response.json()["message"] == "Arquivos enviados com sucesso.":
                st.success(f"Imagens de {img_type} enviadas com sucesso!")
                response =requests.get(f"{FASTAPI_URL}/get_sheets", params={"uuid":uuid_str})
                if response.status_code == 200:
                    st.success("Tabela gerada com sucesso!")
                    download_excel_from_api(f"{FASTAPI_URL}/download/{uuid_str}/output")
                else:
                    st.error(f"Erro ao gerar a tabela: {response.json()['detail']}")
            else:
                st.error(f"Erro ao enviar imagens de {img_type}: {response.json()['message']}")

            # ... Continue seu processamento (enviar para Vertex AI, etc.)
    else:
        st.warning("Selecione algum arquivo para enviar")
      