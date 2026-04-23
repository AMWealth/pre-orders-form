"""Azure Functions для работы с ордерами"""
import azure.functions as func
import logging
import json
from datetime import datetime
from pydantic import ValidationError

from models import OrderCreate, OrderResponse, OrderDetail, ErrorResponse
from db import Database, MarketDatabase
import os

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
logger = logging.getLogger(__name__)


def create_response(status_code: int, body: dict) -> func.HttpResponse:
    """Создание HTTP ответа с CORS заголовками"""
    return func.HttpResponse(
        body=json.dumps(body, default=str),
        status_code=status_code,
        mimetype="application/json",
        headers={
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type, Authorization, x-functions-key'
        }
    )


@app.route(route="orders", methods=["POST", "OPTIONS"])
def create_order(req: func.HttpRequest) -> func.HttpResponse:
    """Создание нового ордера"""
    logger.info('Create order function triggered')
    
    if req.method == "OPTIONS":
        return create_response(200, {})
    
    try:
        req_body = req.get_json()
        order_data = OrderCreate(**req_body)
        
        logger.info(f'Creating order: {order_data.isin}')
        
        # Проверка существования инструмента в market_service
        from db import MarketDatabase
        
        validation_query = """
            SELECT symbol, isin, currencybase, trademode
            FROM market_service.tab_security_mt5
            WHERE trademode = 4
                AND (
                    isin = %s 
                    OR symbol = %s
                )
            LIMIT 1
        """
        
        instrument = MarketDatabase.execute_one(
            validation_query, 
            (order_data.isin, order_data.isin)
        )
        
        if not instrument:
            logger.warning(f'Instrument not found or not tradeable: {order_data.isin}')
            error = ErrorResponse(
                error='Instrument not found',
                details=[f'ISIN/Symbol "{order_data.isin}" not found or not available for trading']
            )
            return create_response(404, error.model_dump())
        
        logger.info(f'Instrument validated: {instrument["symbol"]}')
        # ===== КОНЕЦ ПРОВЕРКИ =====
        
        insert_query = """
            INSERT INTO clients_service.pre_orders (
                consultant_id, consultant_name, client_id, client_name,
                isin, order_type, execution_type, quantity, price,
                expiry_date, comment, created_by, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING order_id, created_date;
        """
        
        params = (
            order_data.consultant_id,
            order_data.consultant_name,
            order_data.client_id,
            order_data.client_name,
            order_data.isin,
            order_data.order_type,
            order_data.execution_type,
            float(order_data.quantity),
            float(order_data.price) if order_data.price else None,
            order_data.expiry_date,
            order_data.comment,
            order_data.created_by or order_data.consultant_name,
            'Pending'
        )
        
        result = Database.execute_one(insert_query, params)
        
        # Аудит лог
        audit_query = """
            INSERT INTO clients_service.order_audit_log (order_id, action, new_status, performed_by, details)
            VALUES (%s, %s, %s, %s, %s)
        """
        Database.execute_query(
            audit_query,
            (result['order_id'], 'ORDER_CREATED', 'Pending',
             order_data.created_by or order_data.consultant_name,
             json.dumps({
                 'isin': order_data.isin,
                 'quantity': str(order_data.quantity),
                 'execution_type': order_data.execution_type
             })),
            fetch=False
        )
        
        logger.info(f'Order created: {result["order_id"]}')
        
        response = OrderResponse(
            success=True,
            order_id=result['order_id'],
            created_date=result['created_date'],
            message='Order created successfully'
        )
        
        return create_response(201, response.model_dump())
        
    except ValidationError as e:
        logger.warning(f'Validation error: {e}')
        error = ErrorResponse(
            error='Validation failed',
            details=[err['msg'] for err in e.errors()]
        )
        return create_response(400, error.model_dump())
    
    except Exception as e:
        logger.error(f'Error: {e}', exc_info=True)
        error = ErrorResponse(error='Internal server error', details=[str(e)])
        return create_response(500, error.model_dump())


@app.route(route="orders", methods=["GET"])
def get_orders(req: func.HttpRequest) -> func.HttpResponse:
    """Получение списка ордеров"""
    logger.info('Get orders function triggered')
    
    try:
        consultant_id = req.params.get('consultant_id')
        status = req.params.get('status')
        limit = min(int(req.params.get('limit', 100)), 1000)
        
        query = """
            SELECT order_id, consultant_id, consultant_name,
                   client_id, client_name, isin, order_type, execution_type,
                   quantity, price, total_amount, status, expiry_date,
                   comment, created_date, created_by, response_date
            FROM clients_service.pre_orders WHERE 1=1
        """
        
        params = []
        if consultant_id:
            query += " AND consultant_id = %s"
            params.append(consultant_id)
        if status:
            query += " AND status = %s"
            params.append(status)
        
        query += " ORDER BY created_date DESC LIMIT %s"
        params.append(limit)
        
        results = Database.execute_query(query, tuple(params))
        orders = [OrderDetail(**row) for row in results]
        
        response = {
            'success': True,
            'count': len(orders),
            'orders': [order.model_dump(mode='json') for order in orders]
        }
        
        return create_response(200, response)
        
    except Exception as e:
        logger.error(f'Error: {e}', exc_info=True)
        error = ErrorResponse(error='Internal server error', details=[str(e)])
        return create_response(500, error.model_dump())


@app.route(route="health", methods=["GET"])
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint"""
    try:
        Database.execute_one("SELECT 1")
        return create_response(200, {
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'database': 'connected'
        })
    except Exception as e:
        return create_response(503, {
            'status': 'unhealthy',
            'error': str(e)
        })
@app.route(route="instruments/securities", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def get_securities(req: func.HttpRequest) -> func.HttpResponse:
    """Получение списка доступных инструментов (акции, облигации)"""
    logger.info('Get securities function triggered')
    
    if req.method == "OPTIONS":
        return create_response(200, {})
    
    try:
        search = req.params.get('search', '')
        currency = req.params.get('currency', '')
        
        logger.info(f'Fetching securities: search={search}, currency={currency}')
        
        query = """
            SELECT DISTINCT
                isin,
                symbol,
                currencybase
            FROM market_service.tab_security_mt5
            WHERE trademode = 4
                AND isin IS NOT NULL
                AND isin != ''
                AND path NOT LIKE '%FX%'
        """
        
        params = []
        if search:
            query += " AND (UPPER(isin) LIKE %s OR UPPER(symbol) LIKE %s)"
            search_pattern = f"%{search.upper()}%"
            params.extend([search_pattern, search_pattern])
        
        if currency:
            query += " AND UPPER(currencybase) = %s"
            params.append(currency.upper())
        
        query += " ORDER BY isin LIMIT 500"
        
        logger.info(f'Executing query with params: {params}')
        
        results = MarketDatabase.execute_query(
            query, 
            tuple(params) if params else None
        )
        
        logger.info(f'Query returned {len(results) if results else 0} results')
        
        if not results:
            results = []
        
        securities = [
            {
                'isin': row['isin'],
                'symbol': row['symbol'],
                'currency': row['currencybase'],
                'display': f"{row['isin']} ({row['currencybase']})"
            }
            for row in results
        ]
        
        logger.info(f'Returning {len(securities)} securities')
        
        return create_response(200, {
            'success': True,
            'count': len(securities),
            'securities': securities
        })
        
    except Exception as e:
        logger.error(f'Error getting securities: {e}', exc_info=True)
        import traceback
        logger.error(f'Traceback: {traceback.format_exc()}')
        error = ErrorResponse(
            error='Internal server error', 
            details=[str(e), traceback.format_exc()]
        )
        return create_response(500, error.model_dump())
        
@app.route(route="instruments/currencies", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)    
def get_currency_pairs(req: func.HttpRequest) -> func.HttpResponse:
    """Получение списка валютных пар для конвертации"""
    logger.info('Get currency pairs function triggered')
    
    if req.method == "OPTIONS":
        return create_response(200, {})
    
    try:
        query = """
            SELECT DISTINCT
                symbol,
                currencybase
            FROM market_service.tab_security_mt5
            WHERE trademode = 4
                AND path LIKE '%FX%'
            ORDER BY symbol
        """
        
        from db import MarketDatabase
        results = MarketDatabase.execute_query(query)
        
        currency_pairs = [
            {
                'symbol': row['symbol'],
                'currency': row['currencybase'],
                'display': row['symbol'].replace('.', ' → ')
            }
            for row in results
        ]
        
        logger.info(f'Retrieved {len(currency_pairs)} currency pairs')
        
        return create_response(200, {
            'success': True,
            'count': len(currency_pairs),
            'currencies': currency_pairs
        })
        
    except Exception as e:
        logger.error(f'Error getting currency pairs: {e}', exc_info=True)
        error = ErrorResponse(error='Internal server error', details=[str(e)])
        return create_response(500, error.model_dump())

@app.route(route="config", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def get_config(req: func.HttpRequest) -> func.HttpResponse:
    """Отдает публичную конфигурацию для frontend"""
    
    if req.method == "OPTIONS":
        return create_response(200, {})
    
    config = {
        'apiUrl': os.getenv('FUNCTION_APP_URL', 'https://amwealth-preorders-api-ana9f3gkajd2bsga.uaenorth-01.azurewebsites.net/') + '/api/orders',
        'apiKey': os.getenv('FRONTEND_API_KEY', '')
    }
    
    return create_response(200, config)
