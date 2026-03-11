-- Initial database setup for Card-to-Crypto Settlement Platform

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Create enums
CREATE TYPE user_role AS ENUM ('admin', 'merchant', 'analyst');
CREATE TYPE transaction_status AS ENUM ('pending', 'processing', 'settled', 'failed', 'review');
CREATE TYPE settlement_status AS ENUM ('pending', 'processing', 'completed', 'failed');
CREATE TYPE fraud_decision AS ENUM ('approve', 'review', 'block');
CREATE TYPE crypto_currency AS ENUM ('USDT', 'USDC', 'BTC', 'ETH', 'BNB');
CREATE TYPE blockchain_network AS ENUM ('ethereum', 'bsc', 'polygon', 'tron');

-- Create indexes and constraints will be added by Alembic migrations