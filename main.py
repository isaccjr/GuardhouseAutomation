import anyio.to_thread
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Query
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
import logging
import re 
import pickle
import anyio


BUCKET_NAME="guardhouse_automation_bucket"
FILE_NAME = "output"
UPLOAD_DIRECTORY = "uploads"  # Diretório para salvar os uploads (localmente)

# Configuração do logger
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

#Configuração do client de storage do Google Cloud Service
storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)



def get_date(exif_data):
    """Pega a data do EXIF de uma imagem."""

    try:
        datetime_original = exif_data.get('EXIF DateTimeOriginal')
        datetime_digitized = exif_data.get('EXIF DateTimeDigitized')
    except:
        print('Erro ao obter metadados EXIF de data')
        raise HTTPException(status_code=500, detail="Erro ao obter metadados EXIF de data")
    if datetime_original:
        return str(datetime_original.values) #converte para string
    elif datetime_digitized:
        return str(datetime_digitized.values) #converte para string
    else:
        return "Data não encontrada nos metadados EXIF"
    
def get_exif(img_bytes):
    with io.BytesIO(img_bytes) as f:
        exif_data = exifread.process_file(f)
    return exif_data

def upload_exif(uuid_str, img_type, file_uuid, data, bucket = bucket):
    pickle_data = pickle.dumps(data)
    file_name = f"{uuid_str}/{img_type}_exif/{file_uuid}"
    blob = bucket.blob(file_name)
    blob.upload_from_string(pickle_data)


async def upload_imgs(imgs, img_type, uuid_str):
    """Uploads imagens para o Cloud Storage diretamente do conteúdo do arquivo."""
    for img in imgs:
        if not img.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"O arquivo '{img.filename}' não é uma imagem.")
        # img agora é um objeto UploadFile do Streamlit
        try:
            file_uuid = str(uuid.uuid4())
            file_name = file_uuid #gera um unique id para cada arquivo para preservar a privacidade
            remote_name = f"{uuid_str}/{img_type}/{file_name}"
            blob = bucket.blob(remote_name)
            try:
                content = await img.read() #lê o conteudo da imagem com bytes
                exif_data = get_exif(content) #pega os metadados do exif
                upload_exif(uuid_str, img_type, file_uuid, exif_data) #upload dos metadados do exif
            except:
                print('Erro ao obter metadados EXIF')
                raise HTTPException(status_code=500, detail="Erro ao obter metadados EXIF")

            #Upload da imagem
            blob.upload_from_file(io.BytesIO(content), content_type=img.content_type) #especifica o content type
            logger.info(f"Arquivo {img.filename} enviado para o GCS")
            url_img = blob.public_url
            print(f"Imagem {file_name} enviada para {url_img}.")

        except Exception as e:
            logger.exception(f"Erro ao processar arquivo {img.filename}: {e}")
            raise HTTPException(status_code=500, detail=f"Erro ao salvar o arquivo '{img.filename}': {str(e)}")


def list_files_gcs(uuid_str, bucket_name=BUCKET_NAME, prefix_docs="documentos/", prefix_plates="placas/", verbose=1):
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
        docs_prefix = uuid_str + "/" + prefix_docs
        plates_prefix = uuid_str + "/" + prefix_plates
        
        if verbose:
            print(f"Prefixo para documentos: {docs_prefix}")
            print(f"Prefixo para placas: {plates_prefix}")

        docs_blobs = list(bucket.list_blobs(prefix=docs_prefix))
        plates_blobs = list(bucket.list_blobs(prefix=plates_prefix))

        if not docs_blobs or len(docs_blobs) == 0:
            raise HTTPException(status_code=404, detail="Nenhum arquivo encontrado na pasta documentos")
        if not plates_blobs or len(plates_blobs) == 0:
            raise HTTPException(status_code=404, detail="Nenhum arquivo encontrado na pasta placas")
        
        if verbose:
            print(f'Encontrados {len(docs_blobs)} arquivos na pasta documentos no bucket {bucket_name}')
            print(f'Encontrados {len(plates_blobs)} arquivos na pasta placas no bucket {bucket_name}')

        # Extrair os nomes dos arquivos (paths)
        try:
            docs_paths = [blob.name for blob in docs_blobs]
            plates_paths = [blob.name for blob in plates_blobs]
        except Exception as e:
            print('Erro ao listar arquivos encontrados no bucket')
            print(e)
            raise HTTPException(status_code=500, detail="Erro ao listar arquivos encontrados no bucket")

        print("Docs_paths, plates_path retornados com sucesso")
        return docs_paths, plates_paths

    except Exception as e:
        print(f"Erro ao listar arquivos no bucket: {e}")
        return [], []


#extraindo metadados
# Recebe um caminho para arquivo de imagem e pega a data do EXIF
def get_image_datetime_gcs(img_blob_name, bucket=bucket):
    """
    Obtém a data e hora de uma imagem armazenada no Google Cloud Storage.

    Args:
        image_url: URL da imagem no Cloud Storage (ex: gs://meu-bucket/imagem.jpg).

    Returns:
        A data e hora da imagem (string), ou uma mensagem de erro.
    """
    print("Obtendo data da imagem...")
    try:
        blob = bucket.blob(img_blob_name)
        if blob.exists():
            print('blob da imagem existe')

            try:
                input_string = img_blob_name
                pattern_plates = r'(.*)/placas/(.*)' 
                pattern_docs = r'(.*)/documentos/(.*)'
                try:
                    match = None
                    match_plates = re.match(pattern_plates, input_string)
                    match_docs = re.match(pattern_docs, input_string)
                    print("match_docs:")
                    print(match_docs)
                    print("match_plates:")
                    print(match_plates)
                except:
                    print("Erro ao obter match")
                if match_plates:
                    print('É UM ARQUIVO EXIF DE PLACA')
                    img_type = "placas"
                    match = match_plates
                if match_docs:
                    print('É UM ARQUIVO EXIF DE DOCUMENTO')
                    img_type = "documentos"
                    match = match_docs
                if match:
                    uuid_str = match.group(1) 
                    uuid_file = match.group(2)
                    if img_type == "placas":
                        exif_path = f"{uuid_str}/placas_exif/{uuid_file}" 
                    elif img_type == "documentos":
                        exif_path = f"{uuid_str}/documentos_exif/{uuid_file}"
                if match==None:
                    print(input_string)
                    print('Erro ao obter tipo de imagem do blob exif')

                #Baixa o arquivo pickle com as tags exif preparadas do exifread    
                try:
                    exif_blob = bucket.blob(exif_path) 
                    if exif_blob.exists(): #Se o blob existe
                        print('blob exif existe') 
                        exif_data = exif_blob.download_as_string() #Faz o download
                    else: #Se não existe o blob do exif
                        print('Exif path:')
                        print(exif_path)
                        print('blob exif não existe')
                except:
                    print("Erro ao obter blob exif")
            except Exception as e:
                print('Erro ao obter blob')
                raise HTTPException(status_code=404, detail="Blob exif não encontrado")
        else:
            print('blob não existe')
        
        try:
            try:
                exif_data = pickle.loads(exif_data)
            except:
                raise HTTPException(status_code=500, detail="Erro ao serealizar o pickle do exif")
            datetime_original = exif_data.get('EXIF DateTimeOriginal')
            datetime_digitized = exif_data.get('EXIF DateTimeDigitized')
        except:
            print('Erro ao obter metadados EXIF de data')
            raise HTTPException(status_code=500, detail="Erro ao obter metadados EXIF de data")

        if datetime_original:
            return str(datetime_original.values) #converte para string
        elif datetime_digitized:
            return str(datetime_digitized.values) #converte para string
        else:
            return "Data não encontrada nos metadados EXIF"

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter data da imagem: {e}")

# Função para converter a string de data em um objeto datetime
def parse_datetime(date_str):
    try:
        return datetime.strptime(date_str, '%Y:%m:%d %H:%M:%S')
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido")

#Função para organizar por data
def sort_by_date(files_path, verbose=1):
    if files_path == []:
        print('File paths vazio')
        raise HTTPException(status_code=404, detail="Nenhum arquivo encontrado na lista de arquivos")
    try:
        files_date = list(map(get_image_datetime_gcs,files_path))
    except:
        print('Erro ao obter data da imagem')
        raise HTTPException(status_code=500, detail="Erro ao obter data da imagem")
    
    print('Files_date:')
    print(files_date)
    #Junta as listas
    files_path_date = list(zip(files_path,files_date))

    try:
        sorted_files_date = sorted(files_path_date, key=lambda x: parse_datetime(x[1]))
    except:
        raise HTTPException(status_code=500, detail="Erro ao organizar os arquivos por data")
    
    if verbose:
        print(f'Organizado {len(sorted_files_date)} arquivos por data')
    return sorted_files_date

#Carrega as imagens
def img_list_loader_gcs(list_of_img_paths, verbose=1):
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
        print(f'Carregando {len(list_of_img_paths)} imagens do Google Cloud Storage')

    for path in list_of_img_paths:
        try:
            print(f'Carregando imagem de {path[0]}')
            blob =  bucket.blob(path[0])
            content = blob.download_as_bytes()  # Baixa o conteúdo do blob como bytes
            img_list.append(content)
        except Exception as e:
            print(f"Erro ao carregar imagem de {path[0]}: {e}")
            raise HTTPException(status_code=500, detail=f"Erro ao carregar imagem de {path[0]}: {e}")

    if verbose:
        print(f'Carregado {len(img_list)} imagens do Google Cloud Storage')
    return img_list

#Converte para o formato que o vertexAI entende
def vertex_img_converter(img):
    print(f'Convertendo imagem para o formato do vertexAI')
    encoded_img = base64.b64encode(img).decode('utf-8')
    vertex_img = Part.from_data(mime_type="image/jpeg",data=base64.b64decode(encoded_img))
    return vertex_img

def save_to_excel(df, uuid_str, file_name="output", bucket=bucket):
    """ Salva um DataFrame pandas no bucket do Google Cloud Storage. """
    # Criar um buffer na memória para o arquivo Excel
    print("Salvando para excel")
    excel_buffer = io.BytesIO()
    # Salvar o DataFrame no buffer
    df.to_excel(excel_buffer, index=False, engine="openpyxl")
    # Resetar o ponteiro do buffer para o início
    excel_buffer.seek(0)
    print('Salvo excel com sucesso')
    # Inicializar o cliente do Storage
    blob = bucket.blob(f"{uuid_str}/output/{file_name}")
    
    # Fazer o upload do buffer para o GCS
    try:
        blob.upload_from_file(excel_buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    except:
        print("Erro ao salvar excel no bucket")
        raise HTTPException(status_code=500, detail="Erro ao salvar excel no bucket")

def convert_to_excel(output, file_name="output"):
    """Converte a saída de texto do Gemini em um DataFrame pandas."""
    try:
        # Converter a saída para um DataFrame do pandas 
        output_io = StringIO(output)
        #Converte a tabela markdown em um dataframe
        df = pd.read_table(output_io, sep="|", skiprows=0, skipinitialspace=True).reindex()
        #Limpa linhas sem nada
        df.dropna(axis=1, how="all", inplace=True)
        df.drop(index=0, inplace=True)
    except Exception as e:
        logger.error("Erro ao converter a saída de texto do Gemini em um DataFrame pandas")
        logger.error(e)
        logger.error(f"Output:{output}")
        print("Erro ao converter a saída de texto do Gemini em um DataFrame pandas")
        raise HTTPException(status_code=500, detail="Erro ao converter a saída de texto do Gemini em um DataFrame pandas")
    return df

async def iter_responses(model, prompt, generation_config, safety_settings): 
        logger.debug("Iniciando iter_responses") 
        try: 
            logger.debug("Chamando Gemini") 
            response = await model.generate_content_async( 
                    prompt, 
                    generation_config=generation_config, 
                    safety_settings=safety_settings
                )
            logger.debug("Chamado com sucesso") 
            logger.debug(f"Resposta do Gemini: {response.text}")
            yield response.text
        except Exception as e: 
            logger.error(f"Erro ao receber resposta do Gemini: {e}") 
            raise HTTPException(status_code=500, detail="Erro ao receber resposta do Gemini")

app = FastAPI()
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)



@app.post("/upload")
async def upload_images(files: List[UploadFile] = File(...), 
                        uuid: str = Form(None), 
                        img_type: str = Form(None)):
    logger.debug(f"Iniciando upload: uuid={uuid}, img_type={img_type}")
    if uuid:
        print('UUID encontrado')
    if not uuid:
        logger.debug("UUID ausente")
        raise HTTPException(status_code=422, detail="UUID é obrigatório")

    if not img_type:
        logger.debug("img_type ausente")
        raise HTTPException(status_code=422, detail="img_type é obrigatório")

    if img_type not in ["documentos", "placas"]:
        logger.debug(f"img_type inválido: {img_type}")
        raise HTTPException(status_code=422, detail="Tipo de imagem inválido")

    logger.debug(f"Número de arquivos recebidos: {len(files)}")

    await upload_imgs(files, img_type, uuid)
    return JSONResponse(content={"message": "Arquivos enviados com sucesso."})

@app.post("/get_sheets")
async def get_sheets(uuid: str = Form(None)):
    try:
        try:
            docs_paths, plates_paths = list_files_gcs(uuid)
            sorted_docs_dates, sorted_plates_dates = sort_by_date(docs_paths), sort_by_date(plates_paths)
            docs_img_list, plates_img_list = img_list_loader_gcs(sorted_docs_dates), img_list_loader_gcs(sorted_plates_dates)
        except:
            raise HTTPException(status_code=500, detail="não foi possivel listar os arquivos")
        #organiza em um lista só primeiro documento depois placa
        try:
            imgs_list =  [item for pair in zip(docs_img_list, plates_img_list) for item in pair]
        except:
            HTTPException(status_code=500, detail="não foi possivel organizar as imagens")
        try:
            vertex_imgs_list = list(map(vertex_img_converter,imgs_list))
        except:
            HTTPException(status_code=500, detail="não foi possivel converter as imagens")

        #Configuração da API VertexAI para usar o projeto e o modelo do gemini
        vertexai.init(project="guardautomation", location="southamerica-east1")

        model = GenerativeModel("gemini-1.5-pro-002",)
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
        output = ""  # Initialize output outside the generator

        async def stream_generator():
            nonlocal output  # Access and modify the outer scope 'output'
            try:
                async for response_text in iter_responses(model, prompt, generation_config, safety_settings):
                    output += response_text  # Accumulate the response
                    yield response_text

            except HTTPException as e:
                raise  # Re-raise HTTPExceptions
            except Exception as e:
                logger.error(f"Erro no iter_responses: {e}")
                raise HTTPException(status_code=500, detail=f"Erro ao gerar a tabela: {e}")
            finally: # This ensures the Excel file is created even if there's an error during streaming
                try:
                    df = convert_to_excel(output)
                    save_to_excel(df, uuid)
                    logger.debug("Tabela salva com sucesso.")
                except Exception as e:
                    logger.error(f"Erro ao processar a saída: {e}")
                    raise HTTPException(status_code=500, detail=f"Erro ao salvar a tabela: {e}")

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    except Exception as e:
        logger.error(f"Erro geral no get_sheets: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar a requisição: {str(e)}")

@app.get("/download")
async def download_file(uuid: str = Form(None), 
                        filename: str = Form(None), 
                        directory: str = Form(None),
                        ):
    try:
        blob_name = f"{uuid}/{directory}/{filename}"
        blob = bucket.blob(blob_name)

        if not blob.exists():
            print('Blob do arquivo excel não existe')
            raise HTTPException(status_code=404, detail="File not found")
        
        content = blob.download_as_bytes()


        def iter_content():  #função generator para otimizar o envio de arquivos grandes
            yield content
        
        return StreamingResponse(iter_content(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename={filename}"})

    except Exception as e:
        print(f"Erro ao carregar arquivo de {blob_name}: {e}") 
        raise HTTPException(status_code=500, detail=f"Erro ao carregar arquivo de {blob_name}: {e}")

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