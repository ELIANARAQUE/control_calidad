-- ============================================================================
-- Esquema completo de ControlCalidad en Supabase (Postgres).
-- Correr una sola vez en: Supabase -> tu proyecto -> SQL Editor -> New query.
--
-- Reemplaza por completo la base SQLite local (data/eventos.db): alertas,
-- transcripciones, eventos de conexion, opciones configurables, y agrega el
-- nuevo sistema de cuentas (usuarios con rol admin/empleado, verificacion
-- facial, y la clave de super-admin para poder registrar administradores).
--
-- El backend usa la SERVICE ROLE KEY (no la anon key) para todas sus
-- operaciones -es un servidor de confianza, no un cliente de navegador-, asi
-- que Row Level Security se deja DESACTIVADO en estas tablas: el control de
-- acceso real lo hace el backend (tokens de sesion + verificacion de rol),
-- no Postgres. Si en el futuro algo llega a llamar a Supabase directo desde
-- el navegador con la anon key, ahi si hay que activar RLS con politicas.
-- ============================================================================

create extension if not exists pgcrypto;  -- para gen_random_uuid()

-- --------------------------------------------------------------------------
-- Catalogo de tipos de documento (poblado abajo, editable despues sin tocar
-- codigo -el formulario de registro los carga de aqui, "listas obviamente de
-- base de datos" como se pidio).
-- --------------------------------------------------------------------------
create table if not exists tipos_documento (
    id serial primary key,
    nombre text not null unique
);

insert into tipos_documento (nombre) values
    ('Cédula de ciudadanía'),
    ('Cédula de extranjería'),
    ('Tarjeta de identidad'),
    ('Pasaporte')
on conflict (nombre) do nothing;

-- --------------------------------------------------------------------------
-- Clave de super-admin: se pide al marcar "Administrador" en el registro,
-- para que no cualquiera pueda crearse una cuenta de admin. Se guarda
-- hasheada (bcrypt), nunca en texto plano. El hash de abajo corresponde a
-- "SAdmin123" (el valor pedido); cambialo cuando quieras generando un hash
-- nuevo con bcrypt y actualizando esta fila.
-- --------------------------------------------------------------------------
create table if not exists super_admin (
    id serial primary key,
    clave_hash text not null,
    actualizado_en timestamptz not null default now()
);

insert into super_admin (id, clave_hash)
values (1, '$2b$12$k.FHo7mVbIYcojLCa7yzJu3S/Gbg.LtVcdWqhl8r2CYxSo39UUeu2')
on conflict (id) do nothing;

-- --------------------------------------------------------------------------
-- Usuarios (empleados y administradores). Datos sensibles (numero de
-- documento, correo) se guardan cifrados con `cryptography` (Fernet) desde
-- el backend -esta tabla solo ve el texto cifrado-, mas una columna de hash
-- (SHA-256) determinista para poder buscar/validar duplicados sin tener que
-- descifrar todo. La clave de acceso se guarda con bcrypt (nunca reversible).
-- El embedding facial (para el login con verificacion de rostro) se guarda
-- como jsonb; la foto de registro se sube a Supabase Storage y aqui solo se
-- guarda su ruta/URL.
-- --------------------------------------------------------------------------
create table if not exists usuarios (
    id uuid primary key default gen_random_uuid(),
    nombre text not null,
    tipo_documento_id integer not null references tipos_documento(id),
    numero_documento_cifrado text not null,
    numero_documento_hash text not null unique,
    correo_cifrado text not null,
    correo_hash text not null unique,
    clave_hash text not null,
    rol text not null check (rol in ('empleado', 'admin')),
    foto_url text,
    fotos jsonb,  -- {"frontal": ruta, "izquierda": ruta, "derecha": ruta} en Storage
    rostro_embedding jsonb,  -- {"frontal": [...], "izquierda": [...], "derecha": [...]}
    creado_en timestamptz not null default now()
);

create index if not exists idx_usuarios_rol on usuarios(rol);

-- --------------------------------------------------------------------------
-- Lo que antes vivia en SQLite: eventos de conexion, alertas, transcripciones
-- y las opciones configurables de sede/modulo. Mismos campos que antes, solo
-- que ahora en Postgres.
-- --------------------------------------------------------------------------
create table if not exists eventos_conexion (
    id bigserial primary key,
    estacion_id text not null,
    empleado_nombre text,
    tipo text not null check (tipo in ('conexion', 'desconexion')),
    "timestamp" timestamptz not null default now(),
    sede text,
    modulo text,
    acepto_habeas_data boolean
);

create index if not exists idx_eventos_conexion_estacion on eventos_conexion(estacion_id);
create index if not exists idx_eventos_conexion_timestamp on eventos_conexion("timestamp");

create table if not exists alertas (
    id bigserial primary key,
    estacion_id text not null,
    tipo text not null default 'postura',
    detalle text not null,
    "timestamp" timestamptz not null default now(),
    veredicto text,
    captura_path text
);

create index if not exists idx_alertas_estacion on alertas(estacion_id);
create index if not exists idx_alertas_timestamp on alertas("timestamp");

create table if not exists transcripciones (
    id bigserial primary key,
    estacion_id text not null,
    texto text not null,
    "timestamp" timestamptz not null default now()
);

create index if not exists idx_transcripciones_estacion on transcripciones(estacion_id);
create index if not exists idx_transcripciones_timestamp on transcripciones("timestamp");

create table if not exists emociones (
    id bigserial primary key,
    estacion_id text not null,
    emocion text not null,
    probabilidad real,
    "timestamp" timestamptz not null default now()
);

create index if not exists idx_emociones_estacion on emociones(estacion_id);
create index if not exists idx_emociones_timestamp on emociones("timestamp");

create table if not exists opciones_configurables (
    tipo text not null,
    valor text not null,
    orden integer not null,
    primary key (tipo, valor)
);

insert into opciones_configurables (tipo, valor, orden) values
    ('sede', 'Sede Principal', 0),
    ('sede', 'Campus Norte', 1),
    ('sede', 'Atención Virtual', 2),
    ('modulo', 'Admisiones y Registro', 0),
    ('modulo', 'Soporte Técnico', 1),
    ('modulo', 'Financiera', 2)
on conflict (tipo, valor) do nothing;

-- --------------------------------------------------------------------------
-- Bucket de Storage para las fotos de registro (rostro). Crear tambien desde
-- el dashboard (Storage -> New bucket -> nombre "fotos-empleados", privado)
-- si esta sentencia no alcanza a correr por permisos del SQL editor.
-- --------------------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('fotos-empleados', 'fotos-empleados', false)
on conflict (id) do nothing;
