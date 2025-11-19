"""
📦 Módulo de Rastreamento - Melhor Rastreio API
===============================================
Módulo para consulta de rastreamento via API GraphQL do Melhor Rastreio
Baseado na engenharia reversa realizada pelo skeleton_killer.py

Uso:
    from tracking import MelhorRastreio

    tracker = MelhorRastreio()
    resultado = tracker.rastrear("LTM-95710601920")
    print(resultado)

Autor: Engenharia Reversa - skeleton_killer.py
Data: 30/10/2025
Atualização: 19/11/2025 - Adicionado suporte para eventos traduzidos completos
"""

import requests
import json
from datetime import datetime
from typing import Dict, List, Optional, Union


class MelhorRastreioException(Exception):
    """Exceção personalizada para erros do MelhorRastreio"""
    pass


class MelhorRastreio:
    """
    Cliente para API GraphQL do Melhor Rastreio

    Esta classe fornece uma interface simples para consultar
    dados de rastreamento usando a API descoberta via engenharia reversa.

    NOVO: Agora inclui eventos traduzidos completos com título e descrição formatados!
    """

    # Cache de eventos traduzidos (carregado uma vez na primeira execução)
    _eventos_traduzidos_cache = None

    def __init__(self, timeout: int = 30, carregar_traducoes: bool = True):
        """
        Inicializa o cliente MelhorRastreio

        Args:
            timeout (int): Timeout para requisições em segundos (padrão: 30)
            carregar_traducoes (bool): Se True, carrega os eventos traduzidos (padrão: True)
        """
        self.api_url = "https://api.melhorrastreio.com.br/graphql"
        self.timeout = timeout
        self.carregar_traducoes = carregar_traducoes
        self.headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Origin': 'https://www.melhorrastreio.com.br',
            'Referer': 'https://www.melhorrastreio.com.br/',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8'
        }

        # Carregar traduções na primeira inicialização
        if self.carregar_traducoes and MelhorRastreio._eventos_traduzidos_cache is None:
            self._carregar_eventos_traduzidos()
    
    def rastrear(self, codigo: str) -> Dict:
        """
        Rastreia um código de envio

        Args:
            codigo (str): Código de rastreamento

        Returns:
            Dict: Dados de rastreamento estruturados com eventos traduzidos completos

        Raises:
            MelhorRastreioException: Em caso de erro na consulta

        Example:
            >>> tracker = MelhorRastreio()
            >>> resultado = tracker.rastrear("LTM-95710601920")
            >>> print(resultado['eventos'][0]['titulo_completo'])
            'Seu pacote saiu para entrega'
            >>> print(resultado['eventos'][0]['descricao_completa'])
            'Seu pacote acabou de sair da unidade e em breve será entregue ao destinatário'
        """
        try:
            # Fazer consulta GraphQL
            dados_brutos = self._consultar_graphql(codigo)

            # Processar e estruturar dados
            dados_estruturados = self._processar_dados(dados_brutos, codigo)

            return dados_estruturados

        except requests.exceptions.RequestException as e:
            raise MelhorRastreioException(f"Erro de rede: {e}")
        except Exception as e:
            raise MelhorRastreioException(f"Erro inesperado: {e}")

    def _carregar_eventos_traduzidos(self) -> None:
        """
        Carrega todos os eventos traduzidos da API (cache global)

        Esta função busca os 131 eventos traduzidos disponíveis na API
        e armazena em cache para uso posterior.
        """
        try:
            query = {
                "query": """
                query {
                    findAllTranslatedTrackingEvents {
                        id
                        title
                        description
                        flag
                        status
                        referenceId
                    }
                }
                """
            }

            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=query,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                if 'data' in data and 'findAllTranslatedTrackingEvents' in data['data']:
                    eventos = data['data']['findAllTranslatedTrackingEvents']
                    # Criar dicionário para lookup rápido por referenceId
                    MelhorRastreio._eventos_traduzidos_cache = {
                        evento['referenceId']: evento
                        for evento in eventos
                        if evento.get('referenceId')
                    }
        except Exception as e:
            # Se falhar ao carregar traduções, continua sem elas
            MelhorRastreio._eventos_traduzidos_cache = {}
    
    def _consultar_graphql(self, codigo: str) -> Dict:
        """
        Executa consulta GraphQL na API com TODOS os campos disponíveis

        Args:
            codigo (str): Código de rastreamento

        Returns:
            Dict: Resposta bruta da API

        Raises:
            MelhorRastreioException: Em caso de erro na API
        """
        query = {
            "query": """
            query($tracker: TrackerTrackingCode!) {
                findByTrackingCode(tracker: $tracker) {
                    trackers {
                        trackingCode
                        type
                        shippingService
                        trackerInternalId
                    }
                    trackingEvents {
                        trackingCode
                        createdAt
                        registeredAt
                        source
                        translatedEventId
                        status
                        title
                        description
                        notes
                        from
                        to
                        additionalInfo
                        notifiedAt
                        trackerType
                        location {
                            zipcode
                            address
                            locality
                            number
                            complement
                            city
                            state
                            country
                        }
                    }
                }
            }
            """,
            "variables": {
                "tracker": {
                    "trackingCode": codigo
                }
            }
        }

        response = requests.post(
            self.api_url,
            headers=self.headers,
            json=query,
            timeout=self.timeout
        )

        if response.status_code != 200:
            raise MelhorRastreioException(f"Erro HTTP {response.status_code}: {response.text}")

        data = response.json()

        # Verificar erros da API
        if 'errors' in data:
            erro = data['errors'][0]['message']
            codigo_erro = data['errors'][0].get('statusCode', 'UNKNOWN')
            raise MelhorRastreioException(f"Erro da API ({codigo_erro}): {erro}")

        return data['data']['findByTrackingCode']
    
    def _processar_dados(self, dados_brutos: Dict, codigo_original: str) -> Dict:
        """
        Processa dados brutos da API em formato estruturado
        
        Args:
            dados_brutos (Dict): Dados brutos da API
            codigo_original (str): Código original consultado
            
        Returns:
            Dict: Dados estruturados
        """
        if not dados_brutos:
            return self._resultado_vazio(codigo_original)
        
        # Extrair informações do tracker
        trackers = dados_brutos.get('trackers', [])
        eventos = dados_brutos.get('trackingEvents', [])
        
        # Informações básicas
        info_basica = self._extrair_info_basica(trackers, codigo_original)
        
        # Processar eventos
        eventos_processados = self._processar_eventos(eventos)
        
        # Determinar status atual
        status_atual = self._determinar_status_atual(eventos_processados)
        
        # Montar resultado final
        resultado = {
            **info_basica,
            'total_eventos': len(eventos_processados),
            'status_atual': status_atual,
            'ultima_atualizacao': eventos_processados[0]['data_registro'] if eventos_processados else None,
            'eventos': eventos_processados,
            'consulta_realizada_em': datetime.now().isoformat(),
            'sucesso': True
        }
        
        return resultado
    
    def _extrair_info_basica(self, trackers: List[Dict], codigo_original: str) -> Dict:
        """Extrai informações básicas do tracker"""
        if not trackers:
            return {
                'codigo_original': codigo_original,
                'codigos_rastreamento': [],
                'transportadoras': [],
                'servico_envio': None,
                'id_interno': None
            }

        # Extrair todos os códigos e transportadoras
        codigos = [t.get('trackingCode') for t in trackers if t.get('trackingCode')]
        transportadoras = list(set([t.get('type') for t in trackers if t.get('type')]))

        # Pegar informações do primeiro tracker
        primeiro = trackers[0]

        return {
            'codigo_original': codigo_original,
            'codigos_rastreamento': codigos,
            'transportadoras': transportadoras,
            'servico_envio': primeiro.get('shippingService'),
            'id_interno': primeiro.get('trackerInternalId')
        }
    
    def _processar_eventos(self, eventos: List[Dict]) -> List[Dict]:
        """
        Processa lista de eventos em formato estruturado COM TRADUÇÕES COMPLETAS

        NOVO: Agora enriquece cada evento com título e descrição formatados!
        """
        eventos_processados = []

        for evento in eventos:
            # Dados básicos do evento
            evento_estruturado = {
                'data_registro': evento.get('registeredAt'),
                'data_criacao': evento.get('createdAt'),
                'data_notificacao': evento.get('notifiedAt'),
                'titulo': evento.get('title'),
                'descricao': evento.get('description'),
                'status_codigo': evento.get('status'),
                'origem': evento.get('from'),
                'destino': evento.get('to'),
                'informacao_adicional': evento.get('additionalInfo'),
                'observacoes': evento.get('notes'),
                'fonte': evento.get('source'),
                'tipo_tracker': evento.get('trackerType'),
                'translated_event_id': evento.get('translatedEventId'),
                'localizacao': self._processar_localizacao(evento.get('location')),
                'rota': self._formatar_rota(evento.get('from'), evento.get('to'))
            }

            # NOVO: Enriquecer com tradução completa
            if self.carregar_traducoes and evento.get('translatedEventId'):
                traducao = self._obter_traducao(evento['translatedEventId'])
                if traducao:
                    evento_estruturado.update({
                        'titulo_completo': traducao.get('title'),
                        'descricao_completa': traducao.get('description'),
                        'flag': traducao.get('flag'),
                        'status_traducao': traducao.get('status')
                    })

            eventos_processados.append(evento_estruturado)

        # Ordenar por data (mais recente primeiro)
        eventos_processados.sort(
            key=lambda x: x['data_registro'] or '',
            reverse=True
        )

        return eventos_processados

    def _obter_traducao(self, translated_event_id: int) -> Optional[Dict]:
        """
        Obtém a tradução completa de um evento pelo ID

        Args:
            translated_event_id (int): ID do evento traduzido

        Returns:
            Optional[Dict]: Dados da tradução ou None se não encontrado
        """
        if MelhorRastreio._eventos_traduzidos_cache is None:
            return None

        return MelhorRastreio._eventos_traduzidos_cache.get(translated_event_id)
    
    def _processar_localizacao(self, location: Optional[Dict]) -> Optional[Dict]:
        """
        Processa dados de localização completos

        NOVO: Retorna todos os campos disponíveis da localização
        """
        if not location:
            return None

        # Montar endereço completo
        partes_endereco = []
        if location.get('address'):
            partes_endereco.append(location['address'])
        if location.get('number'):
            partes_endereco.append(location['number'])
        if location.get('complement'):
            partes_endereco.append(location['complement'])

        # Montar cidade/estado/país
        partes_localizacao = []
        if location.get('city'):
            partes_localizacao.append(location['city'])
        if location.get('state'):
            partes_localizacao.append(location['state'])
        if location.get('country'):
            partes_localizacao.append(location['country'])

        return {
            'cep': location.get('zipcode'),
            'endereco': ', '.join(partes_endereco) if partes_endereco else None,
            'localidade': location.get('locality'),
            'cidade': location.get('city'),
            'estado': location.get('state'),
            'pais': location.get('country'),
            'endereco_completo': ', '.join(partes_localizacao) if partes_localizacao else None
        }
    
    def _formatar_rota(self, origem: Optional[str], destino: Optional[str]) -> str:
        """Formata rota de origem para destino"""
        origem = origem or '?'
        destino = destino or '?'
        return f"{origem} → {destino}"
    
    def _determinar_status_atual(self, eventos: List[Dict]) -> Optional[str]:
        """
        Determina o status atual baseado no último evento

        NOVO: Prioriza título completo da tradução
        """
        if not eventos:
            return None

        ultimo_evento = eventos[0]  # Mais recente (já ordenado)

        # Priorizar título completo traduzido, depois título, depois descrição
        return (
            ultimo_evento.get('titulo_completo') or
            ultimo_evento.get('titulo') or
            ultimo_evento.get('descricao')
        )
    
    def _resultado_vazio(self, codigo_original: str) -> Dict:
        """Retorna resultado vazio para códigos não encontrados"""
        return {
            'codigo_original': codigo_original,
            'codigos_rastreamento': [],
            'transportadoras': [],
            'servico_envio': None,
            'id_interno': None,
            'total_eventos': 0,
            'status_atual': None,
            'ultima_atualizacao': None,
            'eventos': [],
            'consulta_realizada_em': datetime.now().isoformat(),
            'sucesso': False,
            'erro': 'Código não encontrado na base de dados'
        }


# Funções de conveniência para uso direto
def rastrear(codigo: str, timeout: int = 30, carregar_traducoes: bool = True) -> Dict:
    """
    Função de conveniência para rastreamento direto

    Args:
        codigo (str): Código de rastreamento
        timeout (int): Timeout em segundos
        carregar_traducoes (bool): Se True, inclui traduções completas dos eventos

    Returns:
        Dict: Dados de rastreamento com eventos traduzidos completos

    Example:
        >>> import tracking
        >>> resultado = tracking.rastrear("LTM-95710601920")
        >>> print(resultado['status_atual'])
        'Seu pacote saiu para entrega'
        >>> print(resultado['eventos'][0]['descricao_completa'])
        'Seu pacote acabou de sair da unidade e em breve será entregue ao destinatário'
    """
    tracker = MelhorRastreio(timeout=timeout, carregar_traducoes=carregar_traducoes)
    return tracker.rastrear(codigo)


def rastrear_json(codigo: str, indent: int = 2, ensure_ascii: bool = False) -> str:
    """
    Retorna resultado do rastreamento como JSON string

    Args:
        codigo (str): Código de rastreamento
        indent (int): Indentação do JSON
        ensure_ascii (bool): Forçar ASCII no JSON

    Returns:
        str: JSON string com dados de rastreamento completos

    Example:
        >>> import tracking
        >>> json_resultado = tracking.rastrear_json("LTM-95710601920")
        >>> print(json_resultado)
    """
    resultado = rastrear(codigo)
    return json.dumps(resultado, indent=indent, ensure_ascii=ensure_ascii)


# Informações do módulo
__version__ = "2.0.0"
__author__ = "Engenharia Reversa - skeleton_killer.py + Claude Code"
__description__ = "Módulo para rastreamento via API GraphQL do Melhor Rastreio com eventos traduzidos completos"

# Exportar classes e funções principais
__all__ = [
    'MelhorRastreio',
    'MelhorRastreioException',
    'rastrear',
    'rastrear_json'
]