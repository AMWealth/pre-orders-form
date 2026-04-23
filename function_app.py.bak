"""Azure Functions для работы с ордерами"""
import azure.functions as func
import logging
import json
from datetime import datetime
from pydantic import ValidationError

from models import OrderCreate, OrderResponse, OrderDetail, ErrorResponse
from db import Database

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
        
        insert_query = """
            INSERT INTO orders (
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
            INSERT INTO order_audit_log (order_id, action, new_status, performed_by, details)
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
            FROM orders WHERE 1=1
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
