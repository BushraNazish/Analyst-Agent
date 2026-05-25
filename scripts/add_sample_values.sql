-- ============================================================
-- SAMPLE VALUES ENHANCEMENT FOR DATA DICTIONARY
-- ============================================================
-- 
-- WHY THIS MATTERS:
-- -----------------
-- When the LLM generates SQL with WHERE clauses, it needs to know
-- what valid values exist in the database. Without sample values,
-- the LLM will guess — and often guess wrong.
--
-- EXAMPLE OF THE PROBLEM:
--   User asks: "Show me orders from São Paulo"
--   
--   Without sample_values → LLM might generate:
--     WHERE customer_state = 'São Paulo'      ← WRONG (it's 'SP')
--     WHERE customer_city = 'sao paulo'       ← WRONG (it's 'sao paulo' but case matters)
--   
--   With sample_values = 'SP, RJ, MG, RS, PR, ...' → LLM generates:
--     WHERE customer_state = 'SP'             ← CORRECT
--
-- WHAT THIS SCRIPT DOES:
-- ----------------------
-- 1. Adds a `sample_values` column to data_dictionary
-- 2. Populates it with REAL values from each column:
--    - For LOW cardinality columns (≤20 distinct values): ALL distinct values
--    - For HIGH cardinality columns (>20 distinct): 5 representative samples
--    - For measure/numeric columns: min, max, and avg values
-- ============================================================


-- STEP 1: Add the sample_values column
ALTER TABLE data_dictionary 
ADD COLUMN IF NOT EXISTS sample_values TEXT;


-- STEP 2: Populate sample_values for each column
-- ============================================================
-- CUSTOMERS TABLE
-- ============================================================

-- customer_id (high cardinality — just show format examples)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT customer_id, ', ' ORDER BY customer_id) 
    FROM (SELECT DISTINCT customer_id FROM customers LIMIT 3) sub
) WHERE table_name = 'customers' AND column_name = 'customer_id';

-- customer_unique_id (high cardinality — format examples)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT customer_unique_id, ', ' ORDER BY customer_unique_id) 
    FROM (SELECT DISTINCT customer_unique_id FROM customers LIMIT 3) sub
) WHERE table_name = 'customers' AND column_name = 'customer_unique_id';

-- customer_zip_code_prefix (high cardinality — samples)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT customer_zip_code_prefix, ', ' ORDER BY customer_zip_code_prefix) 
    FROM (SELECT DISTINCT customer_zip_code_prefix FROM customers LIMIT 5) sub
) WHERE table_name = 'customers' AND column_name = 'customer_zip_code_prefix';

-- customer_city (high cardinality — top 10 by frequency)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(city, ', ') FROM (
        SELECT customer_city AS city FROM customers 
        GROUP BY customer_city ORDER BY COUNT(*) DESC LIMIT 10
    ) sub
) WHERE table_name = 'customers' AND column_name = 'customer_city';

-- customer_state (low cardinality — ALL values)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT customer_state, ', ' ORDER BY customer_state) FROM customers
) WHERE table_name = 'customers' AND column_name = 'customer_state';


-- ============================================================
-- ORDERS TABLE
-- ============================================================

-- order_id (high cardinality — format examples)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT order_id, ', ' ORDER BY order_id) 
    FROM (SELECT DISTINCT order_id FROM orders LIMIT 3) sub
) WHERE table_name = 'orders' AND column_name = 'order_id';

-- customer_id in orders (FK — skip, same format as customers)
UPDATE data_dictionary SET sample_values = 'Same format as customers.customer_id'
WHERE table_name = 'orders' AND column_name = 'customer_id';

-- order_status (low cardinality — ALL values)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT order_status, ', ' ORDER BY order_status) FROM orders
) WHERE table_name = 'orders' AND column_name = 'order_status';

-- order_purchase_timestamp (date range)
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || MIN(order_purchase_timestamp)::date || ' to ' || MAX(order_purchase_timestamp)::date FROM orders
) WHERE table_name = 'orders' AND column_name = 'order_purchase_timestamp';

-- order_approved_at (date range)
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || MIN(order_approved_at)::date || ' to ' || MAX(order_approved_at)::date FROM orders
) WHERE table_name = 'orders' AND column_name = 'order_approved_at';

-- order_delivered_carrier_date
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || MIN(order_delivered_carrier_date)::date || ' to ' || MAX(order_delivered_carrier_date)::date FROM orders
) WHERE table_name = 'orders' AND column_name = 'order_delivered_carrier_date';

-- order_delivered_customer_date
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || MIN(order_delivered_customer_date)::date || ' to ' || MAX(order_delivered_customer_date)::date FROM orders
) WHERE table_name = 'orders' AND column_name = 'order_delivered_customer_date';

-- order_estimated_delivery_date
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || MIN(order_estimated_delivery_date)::date || ' to ' || MAX(order_estimated_delivery_date)::date FROM orders
) WHERE table_name = 'orders' AND column_name = 'order_estimated_delivery_date';


-- ============================================================
-- ORDER_ITEMS TABLE
-- ============================================================

-- order_id (FK)
UPDATE data_dictionary SET sample_values = 'Same format as orders.order_id'
WHERE table_name = 'order_items' AND column_name = 'order_id';

-- order_item_id (sequential number)
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || MIN(order_item_id) || ' to ' || MAX(order_item_id) FROM order_items
) WHERE table_name = 'order_items' AND column_name = 'order_item_id';

-- product_id (FK — format examples)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT product_id, ', ' ORDER BY product_id) 
    FROM (SELECT DISTINCT product_id FROM order_items LIMIT 3) sub
) WHERE table_name = 'order_items' AND column_name = 'product_id';

-- seller_id (FK — format examples)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT seller_id, ', ' ORDER BY seller_id) 
    FROM (SELECT DISTINCT seller_id FROM order_items LIMIT 3) sub
) WHERE table_name = 'order_items' AND column_name = 'seller_id';

-- shipping_limit_date
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || MIN(shipping_limit_date)::date || ' to ' || MAX(shipping_limit_date)::date FROM order_items
) WHERE table_name = 'order_items' AND column_name = 'shipping_limit_date';

-- price (numeric — show min/max/avg)
UPDATE data_dictionary SET sample_values = (
    SELECT 'Min: ' || ROUND(MIN(price)::numeric, 2) || ', Max: ' || ROUND(MAX(price)::numeric, 2) || ', Avg: ' || ROUND(AVG(price)::numeric, 2) FROM order_items
) WHERE table_name = 'order_items' AND column_name = 'price';

-- freight_value (numeric)
UPDATE data_dictionary SET sample_values = (
    SELECT 'Min: ' || ROUND(MIN(freight_value)::numeric, 2) || ', Max: ' || ROUND(MAX(freight_value)::numeric, 2) || ', Avg: ' || ROUND(AVG(freight_value)::numeric, 2) FROM order_items
) WHERE table_name = 'order_items' AND column_name = 'freight_value';


-- ============================================================
-- ORDER_PAYMENTS TABLE
-- ============================================================

-- order_id (FK)
UPDATE data_dictionary SET sample_values = 'Same format as orders.order_id'
WHERE table_name = 'order_payments' AND column_name = 'order_id';

-- payment_sequential
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || MIN(payment_sequential) || ' to ' || MAX(payment_sequential) FROM order_payments
) WHERE table_name = 'order_payments' AND column_name = 'payment_sequential';

-- payment_type (low cardinality — ALL values)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT payment_type, ', ' ORDER BY payment_type) FROM order_payments
) WHERE table_name = 'order_payments' AND column_name = 'payment_type';

-- payment_installments
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || MIN(payment_installments) || ' to ' || MAX(payment_installments) || ', Avg: ' || ROUND(AVG(payment_installments)::numeric, 1) FROM order_payments
) WHERE table_name = 'order_payments' AND column_name = 'payment_installments';

-- payment_value
UPDATE data_dictionary SET sample_values = (
    SELECT 'Min: ' || ROUND(MIN(payment_value)::numeric, 2) || ', Max: ' || ROUND(MAX(payment_value)::numeric, 2) || ', Avg: ' || ROUND(AVG(payment_value)::numeric, 2) FROM order_payments
) WHERE table_name = 'order_payments' AND column_name = 'payment_value';


-- ============================================================
-- ORDER_REVIEWS TABLE
-- ============================================================

-- review_id (high cardinality — format examples)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT review_id, ', ' ORDER BY review_id) 
    FROM (SELECT DISTINCT review_id FROM order_reviews LIMIT 3) sub
) WHERE table_name = 'order_reviews' AND column_name = 'review_id';

-- order_id (FK)
UPDATE data_dictionary SET sample_values = 'Same format as orders.order_id'
WHERE table_name = 'order_reviews' AND column_name = 'order_id';

-- review_score (low cardinality — ALL values)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT review_score::text, ', ' ORDER BY review_score::text) FROM order_reviews
) WHERE table_name = 'order_reviews' AND column_name = 'review_score';

-- review_comment_title (high cardinality — samples)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(title, ', ') FROM (
        SELECT DISTINCT review_comment_title AS title FROM order_reviews 
        WHERE review_comment_title IS NOT NULL AND review_comment_title != '' LIMIT 3
    ) sub
) WHERE table_name = 'order_reviews' AND column_name = 'review_comment_title';

-- review_comment_message (free text — just note it)
UPDATE data_dictionary SET sample_values = 'Free-form text in Portuguese; highly variable'
WHERE table_name = 'order_reviews' AND column_name = 'review_comment_message';

-- review_creation_date
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || MIN(review_creation_date)::date || ' to ' || MAX(review_creation_date)::date FROM order_reviews
) WHERE table_name = 'order_reviews' AND column_name = 'review_creation_date';

-- review_answer_timestamp
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || MIN(review_answer_timestamp)::date || ' to ' || MAX(review_answer_timestamp)::date FROM order_reviews
) WHERE table_name = 'order_reviews' AND column_name = 'review_answer_timestamp';


-- ============================================================
-- PRODUCTS TABLE
-- ============================================================

-- product_id (high cardinality — format examples)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT product_id, ', ' ORDER BY product_id) 
    FROM (SELECT DISTINCT product_id FROM products LIMIT 3) sub
) WHERE table_name = 'products' AND column_name = 'product_id';

-- product_category_name (medium cardinality — top 10 + total count)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(cat, ', ') FROM (
        SELECT product_category_name AS cat FROM products 
        WHERE product_category_name IS NOT NULL
        GROUP BY product_category_name ORDER BY COUNT(*) DESC LIMIT 10
    ) sub
) WHERE table_name = 'products' AND column_name = 'product_category_name';

-- product_name_length
UPDATE data_dictionary SET sample_values = (
    SELECT 'Min: ' || MIN(product_name_length) || ', Max: ' || MAX(product_name_length) || ', Avg: ' || ROUND(AVG(product_name_length)::numeric, 0) FROM products
) WHERE table_name = 'products' AND column_name = 'product_name_length';

-- product_description_length
UPDATE data_dictionary SET sample_values = (
    SELECT 'Min: ' || MIN(product_description_length) || ', Max: ' || MAX(product_description_length) || ', Avg: ' || ROUND(AVG(product_description_length)::numeric, 0) FROM products
) WHERE table_name = 'products' AND column_name = 'product_description_length';

-- product_photos_qty
UPDATE data_dictionary SET sample_values = (
    SELECT 'Min: ' || MIN(product_photos_qty) || ', Max: ' || MAX(product_photos_qty) || ', Avg: ' || ROUND(AVG(product_photos_qty)::numeric, 1) FROM products
) WHERE table_name = 'products' AND column_name = 'product_photos_qty';

-- product_weight_g
UPDATE data_dictionary SET sample_values = (
    SELECT 'Min: ' || MIN(product_weight_g) || 'g, Max: ' || MAX(product_weight_g) || 'g, Avg: ' || ROUND(AVG(product_weight_g)::numeric, 0) || 'g' FROM products
) WHERE table_name = 'products' AND column_name = 'product_weight_g';

-- product_length_cm
UPDATE data_dictionary SET sample_values = (
    SELECT 'Min: ' || MIN(product_length_cm) || 'cm, Max: ' || MAX(product_length_cm) || 'cm, Avg: ' || ROUND(AVG(product_length_cm)::numeric, 0) || 'cm' FROM products
) WHERE table_name = 'products' AND column_name = 'product_length_cm';

-- product_height_cm
UPDATE data_dictionary SET sample_values = (
    SELECT 'Min: ' || MIN(product_height_cm) || 'cm, Max: ' || MAX(product_height_cm) || 'cm, Avg: ' || ROUND(AVG(product_height_cm)::numeric, 0) || 'cm' FROM products
) WHERE table_name = 'products' AND column_name = 'product_height_cm';

-- product_width_cm
UPDATE data_dictionary SET sample_values = (
    SELECT 'Min: ' || MIN(product_width_cm) || 'cm, Max: ' || MAX(product_width_cm) || 'cm, Avg: ' || ROUND(AVG(product_width_cm)::numeric, 0) || 'cm' FROM products
) WHERE table_name = 'products' AND column_name = 'product_width_cm';


-- ============================================================
-- SELLERS TABLE
-- ============================================================

-- seller_id (high cardinality — format examples)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT seller_id, ', ' ORDER BY seller_id) 
    FROM (SELECT DISTINCT seller_id FROM sellers LIMIT 3) sub
) WHERE table_name = 'sellers' AND column_name = 'seller_id';

-- seller_zip_code_prefix
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT seller_zip_code_prefix, ', ' ORDER BY seller_zip_code_prefix) 
    FROM (SELECT DISTINCT seller_zip_code_prefix FROM sellers LIMIT 5) sub
) WHERE table_name = 'sellers' AND column_name = 'seller_zip_code_prefix';

-- seller_city (top 10 by frequency)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(city, ', ') FROM (
        SELECT seller_city AS city FROM sellers 
        GROUP BY seller_city ORDER BY COUNT(*) DESC LIMIT 10
    ) sub
) WHERE table_name = 'sellers' AND column_name = 'seller_city';

-- seller_state (low cardinality — ALL values)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT seller_state, ', ' ORDER BY seller_state) FROM sellers
) WHERE table_name = 'sellers' AND column_name = 'seller_state';


-- ============================================================
-- GEOLOCATION TABLE
-- ============================================================

-- geolocation_zip_code_prefix
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT geolocation_zip_code_prefix, ', ' ORDER BY geolocation_zip_code_prefix) 
    FROM (SELECT DISTINCT geolocation_zip_code_prefix FROM geolocation LIMIT 5) sub
) WHERE table_name = 'geolocation' AND column_name = 'geolocation_zip_code_prefix';

-- geolocation_lat
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || ROUND(MIN(geolocation_lat)::numeric, 4) || ' to ' || ROUND(MAX(geolocation_lat)::numeric, 4) FROM geolocation
) WHERE table_name = 'geolocation' AND column_name = 'geolocation_lat';

-- geolocation_lng
UPDATE data_dictionary SET sample_values = (
    SELECT 'Range: ' || ROUND(MIN(geolocation_lng)::numeric, 4) || ' to ' || ROUND(MAX(geolocation_lng)::numeric, 4) FROM geolocation
) WHERE table_name = 'geolocation' AND column_name = 'geolocation_lng';

-- geolocation_city (top 10)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(city, ', ') FROM (
        SELECT geolocation_city AS city FROM geolocation 
        GROUP BY geolocation_city ORDER BY COUNT(*) DESC LIMIT 10
    ) sub
) WHERE table_name = 'geolocation' AND column_name = 'geolocation_city';

-- geolocation_state (low cardinality — ALL values)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(DISTINCT geolocation_state, ', ' ORDER BY geolocation_state) FROM geolocation
) WHERE table_name = 'geolocation' AND column_name = 'geolocation_state';


-- ============================================================
-- PRODUCT_CATEGORY_NAME_TRANSLATION TABLE
-- ============================================================

-- product_category_name (all Portuguese names — top 10)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(product_category_name, ', ') FROM (
        SELECT product_category_name FROM product_category_name_translation ORDER BY product_category_name LIMIT 10
    ) sub
) WHERE table_name = 'product_category_name_translation' AND column_name = 'product_category_name';

-- product_category_name_english (all English names — top 10)
UPDATE data_dictionary SET sample_values = (
    SELECT string_agg(product_category_name_english, ', ') FROM (
        SELECT product_category_name_english FROM product_category_name_translation ORDER BY product_category_name_english LIMIT 10
    ) sub
) WHERE table_name = 'product_category_name_translation' AND column_name = 'product_category_name_english';


-- ============================================================
-- VERIFICATION: Check the results
-- ============================================================
SELECT table_name, column_name, sample_values 
FROM data_dictionary 
ORDER BY id;
