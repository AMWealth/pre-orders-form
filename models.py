"""Модели данных для валидации"""
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Literal
from datetime import datetime
from decimal import Decimal


class OrderCreate(BaseModel):
    """Модель для создания ордера"""
    consultant_id: str = Field(..., min_length=1, max_length=50)
    consultant_name: str = Field(..., min_length=1, max_length=200)
    client_id: str = Field(..., min_length=1, max_length=50)
    client_name: str = Field(..., min_length=1, max_length=200)
    isin: str = Field(..., min_length=1, max_length=50)
    order_type: Literal['Buy', 'Sell']
    execution_type: Literal['Market', 'Limit']
    quantity: Decimal = Field(..., gt=0)
    price: Optional[Decimal] = Field(None, gt=0, decimal_places=2)
    expiry_date: Optional[datetime] = None
    comment: Optional[str] = Field(None, max_length=500)
    created_by: Optional[str] = None

    @field_validator('isin')
    @classmethod
    def isin_uppercase(cls, v: str) -> str:
        """ISIN или Symbol всегда в верхнем регистре"""
        return v.upper().strip()@field_validator('isin')

    @field_validator('quantity')
    @classmethod
    def quantity_precision(cls, v: Decimal) -> Decimal:
        """Округление quantity до 4 знаков"""
        return round(v, 4)

    @field_validator('price')
    @classmethod
    def price_precision(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        """Округление цены до 2 знаков"""
        if v is not None:
            return round(v, 2)
        return v

    @model_validator(mode='after')
    def validate_limit_order(self):
        """Для Limit ордера цена обязательна"""
        if self.execution_type == 'Limit' and self.price is None:
            raise ValueError('Price is required for Limit orders')
        return self


class OrderResponse(BaseModel):
    """Модель ответа при создании ордера"""
    success: bool
    order_id: Optional[int] = None
    created_date: Optional[datetime] = None
    message: str


class OrderDetail(BaseModel):
    """Модель детальной информации об ордере"""
    order_id: int
    consultant_id: str
    consultant_name: str
    client_id: str
    client_name: str
    isin: str
    order_type: str
    execution_type: str
    quantity: Decimal
    price: Optional[Decimal]
    total_amount: Optional[Decimal]
    status: str
    expiry_date: Optional[datetime]
    comment: Optional[str]
    created_date: datetime
    created_by: Optional[str]
    response_date: Optional[datetime]

    class Config:
        from_attributes = True


class ErrorResponse(BaseModel):
    """Модель ответа с ошибкой"""
    success: bool = False
    error: str
    details: Optional[list] = None
