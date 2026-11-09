-- Synthetic data only. Applied solely to a newly created disposable demo DB.
CREATE TABLE public.products (id integer PRIMARY KEY, name text NOT NULL, price_cents integer NOT NULL);
CREATE TABLE public.customers (id integer PRIMARY KEY, email text NOT NULL);
CREATE TABLE public.orders (id integer PRIMARY KEY, customer_id integer REFERENCES public.customers,
    product_id integer REFERENCES public.products, quantity integer NOT NULL);
INSERT INTO public.products VALUES (1, 'Synthetic notebook', 500), (2, 'Synthetic pen', 100);
INSERT INTO public.customers VALUES (1, 'synthetic-one@example.invalid'), (2, 'synthetic-two@example.invalid');
INSERT INTO public.orders VALUES (1, 1, 1, 2), (2, 2, 2, 3);
