import streamlit as st
import requests
import os
import uuid
import io  # Importei o módulo io para trabalhar com BytesIO
import pandas as pd

FASTAPI_URL = "http://127.0.0.1:8000"

def download_excel_from_api(api_url = FASTAPI_URL, filename="output", directory="output", uuid_str=None):
    try:
        response = requests.get(api_url + "/download", data={"uuid":uuid_str, "filename":filename, "directory":directory, "extention":"xlsx"} , stream=True) #stream=True para lidar com arquivos grandes
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


def processar_respostas(api_url, uuid_str): 
    print("Processando respostas") 
    df = pd.DataFrame(columns=["Placa", "Modelo", "Marca", "Cor", "Nome", "CPF", "RG"]) 
    def add_row(df, Placa, Modelo, Marca, Cor, Nome, CPF, RG): 
        new_row = pd.DataFrame({'Placa': [Placa], 'Modelo': [Modelo], 'Marca': [Marca], 'Cor': [Cor], 'Nome': [Nome], 'CPF': [CPF], 'RG': [RG]}) 
        return pd.concat([df, new_row], ignore_index=True) 
    response = requests.post(api_url, data={"uuid": uuid_str}, stream=True) 
    if response.status_code == 200: 
        table_placeholder = st.empty() # Reserva espaço para a tabela 
        for idx, line in enumerate(response.iter_lines()): 
            if idx < 2: continue # Ignora as duas primeiras linhas 
            if line: decoded_line = line.decode('utf-8') 
            line_splited = decoded_line.split("|")[1:-1] 
            line_splited = [item.strip() for item in line_splited] 
            placa, modelo, marca, cor, nome, cpf, rg = line_splited 
            df = add_row(df, placa, modelo, marca, cor, nome, cpf, rg) 
            table_placeholder.dataframe(df) # Atualiza a tabela no espaço reservado 
        return True 
    else:
        st.error(f"Erro ao processar as respostas: {response.json()['detail']}")
# Centralizar a imagem usando colunas 
col1, col2, col3 = st.columns([1, 2, 1]) 
with col2: st.image('imagens/logo.png', use_container_width=True)

# Inicializa o UUID no session_state, se ainda não existir
if "uuid_str" not in st.session_state:
    st.session_state.uuid_str = str(uuid.uuid4())
    st.write("Novo UUID gerado:", st.session_state.uuid_str) #exibe o uuid gerado


st.write('''    O GuardHouse Automation é um aplicativo de automação de guarita, 
         você envia fotos de documentos e de carros e recebe um arquivo excel
         com nome, cpf, rg, placa, modelo do carro e fabricante.
        Tudo automaticamente sem necessidade de anotar ou digitar manualmente.
        Não precisa se preocupar com a ordem de envio dos arquivos.
        O aplicativo vai fazer a inferência de qual documento é de qual motorista pelo horario da foto.
        Então é só tirar as fotos na sequência documento do condutor, foto do carro pegando a placa.
        Tem que ter a mesma quantidade de fotos de documentos e de carros.
        Não use fotos recebidas por WhatsApp ou qualquer aplicativo de mensageria, o aplicativo não tem 
        como inferir a ordem das fotos de arquivos desses aplicativos por excluirem os metadados 
        para sua privacidade.
        Selecione as fotos e aperte em enviar.
        Em poucos segundos você receberá o arquivo com sua tabela.''')

col1, col2, col3 = st.columns([1, 2, 1]) 
with col1: st.image('imagens/exemplo_documento.jpeg', use_container_width=True)
with col3: st.image('imagens/exemplo_placa.jpg', use_container_width=True)

# Campos de upload separados
documentos = st.file_uploader("Selecione os Documentos", accept_multiple_files=True, type=["jpg", "jpeg", "png"])
placas = st.file_uploader("Selecione as Placas", accept_multiple_files=True, type=["jpg", "jpeg", "png"])

if st.button("Enviar Imagens"):
    if documentos and placas:
        uuid_str = st.session_state.uuid_str
        
        doc_sucess_response = False
        plate_sucess_response = False
        response = None

        for img_type, files in [("documentos", documentos), ("placas", placas)]:
            if files:
                multipart_form_data = []
                for file in files:
                    multipart_form_data.append(("files", (file.name, file.read(), file.type)))

                data = {"uuid": uuid_str, "img_type": img_type}

                try:
                    response = requests.post(FASTAPI_URL + "/upload", files=multipart_form_data, data=data) # URL sem parametros
                    response.raise_for_status()
                    st.success(f"Imagens do tipo {img_type} enviadas com sucesso!")
                    if img_type == "documentos":
                        doc_sucess_response = True
                    elif img_type == "placas":
                        plate_sucess_response = True
                except requests.exceptions.RequestException as e:
                    st.error(f"Erro ao enviar imagens do tipo {img_type}: {e}")
            else:
                st.warning(f"Nenhuma imagem do tipo {img_type} selecionada.")


        # Verifica se a mensagem de sucesso está na resposta
        if doc_sucess_response and plate_sucess_response:
            st.success(f"Todas as imagens de enviadas com sucesso!")
            sucesso =processar_respostas(f"{FASTAPI_URL}/get_sheets", uuid_str)
            if sucesso:
                st.success("Tabela gerada com sucesso!")
                download_excel_from_api(uuid_str=uuid_str)
            else:
                st.error(f"Erro ao gerar a tabela: {response.json()['detail']}")
        else:
            if not doc_sucess_response:
                st.error(f"Erro ao enviar imagens de documentos: {response.json()['message']}")
            if not plate_sucess_response:
                st.error(f"Erro ao enviar imagens de placas: {response.json()['message']}")

    else:
        st.warning("Selecione algum arquivo para enviar")
      