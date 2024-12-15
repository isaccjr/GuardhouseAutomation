from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from typing import List
import os
import uuid
from google.cloud import storage
import io  # Importei o módulo io para trabalhar com BytesIO
from io import StringIO
import exifread
from datetime import datetime
import base64
from vertexai.generative_models import GenerativeModel, Part, SafetySetting
import vertexai
import pandas as pd


def upload_imgs(imgs, img_type, uuid_str):
    """Uploads imagens para o Cloud Storage diretamente do conteúdo do arquivo."""

    storage_client = storage.Client()
    bucket_name = "guardhouse_automation_bucket"  # Substitua pelo nome do seu bucket
    bucket = storage_client.bucket(bucket_name)
    remote_files = []

    for img in imgs:
        if not img.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"O arquivo '{img.name}' não é uma imagem.")
        # img agora é um objeto UploadFile do Streamlit
        try:
            file_uuid = str(uuid.uuid4())
            file_name = file_uuid #gera um unique id para cada arquivo para preservar a privacidade
            remote_name = f"{uuid_str}/{img_type}/{file_name}"
            blob = bucket.blob(remote_name)

            # A principal mudança: upload_from_file com BytesIO
            blob.upload_from_file(io.BytesIO(img.getvalue()), content_type=img.type) #especifica o content type

            url_img = blob.public_url
            remote_files.append(url_img)
            print(f"Imagem {file_name} enviada para {url_img}.")

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao salvar o arquivo '{img.name}': {str(e)}")

    #return remote_files

def list_files_gcs(uuid_str, bucket_name="guardhouse_automation_bucket", prefix_docs="documentos/", prefix_plates="placas/", verbose=1):
    """
    Lista arquivos em um bucket do Google Cloud Storage.

    Args:
        bucket_name: O nome do bucket.
        prefix_docs: O prefixo para arquivos de documentos (equivalente ao diretório "imagens/documentos").
        prefix_plates: O prefixo para arquivos de placas (equivalente ao diretório "imagens/placas").
        verbose: Se 1, imprime informações sobre os arquivos encontrados.

    Returns:
        Uma tupla contendo duas listas: paths dos documentos e paths das placas.
        Retorna tuplas vazias caso ocorra algum erro na listagem.
    """
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)

        docs_blobs = list(bucket.list_blobs(prefix=uuid_str + "/" + prefix_docs))
        plates_blobs = list(bucket.list_blobs(prefix=uuid_str + "/" +prefix_plates))

        if verbose:
            print(f'Encontrados {len(docs_blobs)} arquivos na pasta documentos no bucket {bucket_name}')
            print(f'Encontrados {len(plates_blobs)} arquivos na pasta placas no bucket {bucket_name}')

        # Extrair os nomes dos arquivos (paths)
        docs_paths = [blob.name for blob in docs_blobs]
        plates_paths = [blob.name for blob in plates_blobs]

        return docs_paths, plates_paths

    except Exception as e:  # Captura exceções genéricas para simplificar (melhorar com tratamento específico se necessário)
        print(f"Erro ao listar arquivos do bucket: {e}")
        return [], [] # Retorna tuplas vazias em caso de erro

#extraindo metadados
# Recebe um caminho para arquivo de imagem e pega a data do EXIF
def get_image_datetime_gcs(image_url):
    """
    Obtém a data e hora de uma imagem armazenada no Google Cloud Storage.

    Args:
        image_url: URL da imagem no Cloud Storage (ex: gs://meu-bucket/imagem.jpg).

    Returns:
        A data e hora da imagem (string), ou uma mensagem de erro.
    """
    try:
        storage_client = storage.Client()
        blob = storage_client.get_blob_from_uri(image_url)
        image_bytes = blob.download_as_bytes() #baixa os bytes da imagem

        # Usando io.BytesIO para criar um objeto file-like a partir dos bytes
        with io.BytesIO(image_bytes) as f:
            tags = exifread.process_file(f)

        datetime_original = tags.get('EXIF DateTimeOriginal')
        datetime_digitized = tags.get('EXIF DateTimeDigitized')

        if datetime_original:
            return str(datetime_original.values) #converte para string
        elif datetime_digitized:
            return str(datetime_digitized.values) #converte para string
        else:
            return "Data não encontrada nos metadados EXIF"

    except Exception as e:
        return f"Erro ao obter data da imagem: {e}"

# Função para converter a string de data em um objeto datetime
def parse_datetime(date_str):
    return datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')

#Função para organizar por data
def sort_by_date(files_path, verbose=1):
    files_date = list(map(get_image_datetime_gcs,files_path))
    files_path_date = list(zip(files_path,files_date))
    sorted_files_date = sorted(files_path_date, key=lambda x: parse_datetime(x[1]))
    if verbose:
        print(f'Organizado {len(sorted_files_date)} arquivos por data')
    return sorted_files_date

#Carrega as imagens
def img_list_loader_gcs(list_of_img_urls, verbose=1):
    """
    Carrega imagens a partir de URLs do Google Cloud Storage.

    Args:
        list_of_img_urls: Lista de URLs das imagens no Cloud Storage.
        verbose: Se True, imprime informações durante o carregamento.

    Returns:
        Lista de bytes das imagens carregadas.
    """
    img_list = []
    if verbose:
        print(f'Carregando {len(list_of_img_urls)} imagens do Google Cloud Storage')

    for url in list_of_img_urls:
        try:
            storage_client = storage.Client()
            blob = storage_client.get_blob_from_uri(url)  # Obtém o blob diretamente a partir da URL
            content = blob.download_as_bytes()  # Baixa o conteúdo do blob como bytes
            img_list.append(content)
        except Exception as e:
            print(f"Erro ao carregar imagem de {url}: {e}")

    if verbose:
        print(f'Carregado {len(img_list)} imagens do Google Cloud Storage')
    return img_list

#Converte para o formato que o vertexAI entende
def vertex_img_converter(img):
    encoded_img = base64.b64encode(img).decode('utf-8')
    vertex_img = Part.from_data(mime_type="image/jpeg",data=base64.b64decode(encoded_img))
    return vertex_img

def save_to_excel(df, uuid_str, file_name="output", bucket_name="guardhouse_automation_bucket"):
    # Salvar como arquivo Excel no GSC
    # Criar um buffer na memória para o arquivo Excel
    excel_buffer = io.BytesIO()
    # Salvar o DataFrame no buffer
    df.to_excel(excel_buffer, index=False, engine="openpyxl")
    # Resetar o ponteiro do buffer para o início
    excel_buffer.seek(0)

    # Inicializar o cliente do Storage
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(f"{uuid_str}/output/{file_name}")

    # Fazer o upload do buffer para o GCS
    blob.upload_from_file(excel_buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def convert_to_excel(output, file_name="output"):
    # Converter a saída para um DataFrame do pandas 
    output_io = StringIO(output)
    df = pd.read_table(output_io, sep="|", skiprows=0, skipinitialspace=True).reindex()
    df.dropna(axis=1, how="all", inplace=True)
    df.drop(index=0, inplace=True)
    return df
    

app = FastAPI()

BUCKET_NAME="guardhouse_automation_bucket"
FILE_NAME = "output"
UPLOAD_DIRECTORY = "uploads"  # Diretório para salvar os uploads (localmente)


os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)

@app.post("/upload")
async def upload_images(files: List[UploadFile], uuid: str = Query(None), img_type: str = Query(None)):
    upload_imgs(files, img_type, uuid)
    return JSONResponse(content={"message": "Arquivos enviados com sucesso."})

@app.get("/get_sheets")
async def get_sheets(uuid: str = Query(None)):
    docs_paths, plates_paths = list_files_gcs(uuid)
    sorted_docs_dates, sorted_plates_dates = sort_by_date(docs_paths), sort_by_date(plates_paths)
    docs_img_list, plates_img_list = img_list_loader_gcs(sorted_docs_dates), img_list_loader_gcs(sorted_plates_dates)
    #organiza em um lista só primeiro documento depois placa
    imgs_list =  [item for pair in zip(docs_img_list, plates_img_list) for item in pair]
    vertex_imgs_list = list(map(vertex_img_converter,imgs_list))
    
    #Configuração da API VertexAI para usar o projeto e o modelo do gemini
    vertexai.init(project="guardautomation", location="southamerica-east1")
    model = GenerativeModel(
        "gemini-1.5-pro-002",
    )
    #Prompt para o Gemini tratar as imagens
    text1 = """Crie uma tabela com a placa, modelo, marca do carro, cor,  nome, cpf, rg. 
               Nome, cpf e rg estão nas imagens posteriores a dos carros, 
               a imagem 1 com a 2 e a 3 com a 4 e assim posteriormente.
               rg é geralmente identificado por doc. identidade e seguido pelo orgão emissor, cpf tem 11 digitos.
               Se for possivel retirar algum dados de alguma foto marque a informação com ilegível. 
               Responda somente a tabela nada além da tabela, sem texto antes ou depois da tabela"""

    generation_config = {
    "max_output_tokens": 8192,
    "temperature": 0,
    "top_p": 0.95,
}

    safety_settings = [
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
]

    #Combina as imagens com o texto de prompt
    prompt = vertex_imgs_list + [text1]
    #Chamada da API Vertex AI usando o Gemini como modelo
    responses = model.generate_content(
        prompt,
        generation_config=generation_config,
        safety_settings=safety_settings,
        stream=True,
    )
    # Usar StringIO para capturar a saída do loop de impressão 
    output_buffer = io.StringIO()
    for response in responses:
        output_buffer.write(response.text) 
    # Salvar a saída na variável output 
    output = output_buffer.getvalue() 
    output_buffer.close()
    try:
        df = convert_to_excel(output)
        save_to_excel(df, uuid)
        return JSONResponse(content={"message": "Tabela gerada com sucesso."}, status_code=200)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar a tabela {str(e)}")

@app.get("/download/{uuid}")
async def download_file(uuid: str):
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob_name = f"{uuid}/output/output.xlsx"
        blob = bucket.blob(blob_name)

        if not blob.exists():
            raise HTTPException(status_code=404, detail="File not found")

        def iter_content():  #função generator para otimizar o envio de arquivos grandes
            yield from blob.iter_content()
        
        return StreamingResponse(iter_content(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename={FILE_NAME}.xlsx"})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/files") #rota para listar os arquivos
async def list_files():
    try:
        files = os.listdir(UPLOAD_DIRECTORY)
        files_path = [os.path.join(UPLOAD_DIRECTORY, f) for f in files]
        files_info = [{"name": os.path.basename(file), "size": os.path.getsize(file), "path":file} for file in files_path if os.path.isfile(file)]
        return JSONResponse(content={"files": files_info})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao listar arquivos {str(e)}")

@app.delete("/files/{filename}") #rota para apagar um arquivo
async def delete_file(filename: str):
    try:
      full_path = os.path.join(UPLOAD_DIRECTORY, filename)
      os.remove(full_path)
      return {"message": f"Arquivo {filename} deletado com sucesso."}
    except FileNotFoundError:
      raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    except Exception as e:
      raise HTTPException(status_code=500, detail=f"Erro ao deletar arquivo: {str(e)}")