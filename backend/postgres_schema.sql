-- ============================================================================
-- ControlCalidad — SCHEMA PARA POSTGRES NATIVO (Railway)
--
-- Version derivada de supabase_version_definitiva.sql, adaptada para correr contra un
-- Postgres nativo (Railway) en vez de Supabase. Unica diferencia real: se quito el
-- INSERT a `storage.buckets` (bucket de fotos de registro) porque ese schema es
-- especifico de Supabase Storage y no existe en un Postgres vanilla -las fotos de
-- registro, en la migracion, pasan a guardarse de otra forma (ver fase de migracion de
-- cuentas.py). El resto del schema (tablas, indices, vista, datos iniciales) es identico.
--
-- Como usarlo: psql (o cualquier cliente de Postgres) contra la base de Railway -> pegar
-- todo -> Run. Es seguro correrlo en una base nueva o en una que ya tiene datos (mismas
-- garantias que el script original: no borra ni vacia tablas, crea solo lo que falte).
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
-- como jsonb; la foto de registro (cifrada con Fernet) se guarda en disco
-- local (ver `RUTA_FOTOS_EMPLEADOS` en `app.core.cuentas`) y aqui solo se
-- guarda su ruta RELATIVA a esa carpeta.
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
    fotos jsonb,  -- {"frontal": ruta, "izquierda": ruta, "derecha": ruta} relativas a RUTA_FOTOS_EMPLEADOS
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
    id bigint generated by default as identity unique,
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
-- Diccionario de lenguaje inapropiado (editable desde el panel). Los terminos iniciales se
-- cargan con supabase_lenguaje.sql.
-- --------------------------------------------------------------------------
create table if not exists lenguaje_inapropiado (
    id serial primary key,
    termino text not null unique,
    categoria text not null check (categoria in ('groseria_fuerte', 'groseria_leve', 'mal_trato')),
    creado_en timestamptz not null default now()
);

-- --------------------------------------------------------------------------
-- Pausas de la transmision: el empleado sale a almuerzo o a un break. Una fila
-- por cada pausa (si sale 4 veces a break en una sesion, son 4 filas). Mientras
-- dura, no se analiza ni se transmite nada. `fin` queda vacio mientras la pausa
-- sigue abierta. `sesion_inicio` es la hora de conexion de la sesion en la que
-- ocurrio (el "timestamp" de su fila 'conexion' en eventos_conexion).
-- --------------------------------------------------------------------------
create table if not exists pausas (
    id bigserial primary key,
    estacion_id text not null,
    empleado_nombre text,
    sesion_inicio timestamptz not null,
    tipo text not null check (tipo in ('almuerzo', 'break')),
    inicio timestamptz not null default now(),
    fin timestamptz,
    check (fin is null or fin >= inicio)
);

create index if not exists idx_pausas_estacion on pausas(estacion_id);
create index if not exists idx_pausas_sesion on pausas(estacion_id, sesion_inicio);
create index if not exists idx_pausas_inicio on pausas(inicio);

-- Tiempo TOTAL de cada tipo de pausa por sesion (suma todas las veces que salio).
-- Una pausa todavia abierta cuenta hasta este momento.
create or replace view pausas_por_sesion as
select
    estacion_id,
    empleado_nombre,
    sesion_inicio,
    count(*) filter (where tipo = 'almuerzo') as veces_almuerzo,
    coalesce(sum(extract(epoch from coalesce(fin, now()) - inicio)) filter (where tipo = 'almuerzo'), 0)::int as segundos_almuerzo,
    count(*) filter (where tipo = 'break') as veces_break,
    coalesce(sum(extract(epoch from coalesce(fin, now()) - inicio)) filter (where tipo = 'break'), 0)::int as segundos_break,
    coalesce(sum(extract(epoch from coalesce(fin, now()) - inicio)), 0)::int as segundos_pausa_total
from pausas
group by estacion_id, empleado_nombre, sesion_inicio;


-- ============================================================================
-- Actualizaciones para bases que YA existian (en una base nueva no hacen nada)
-- ============================================================================

-- 3 fotos de registro por usuario (frontal, lateral izquierda, lateral derecha).
alter table usuarios add column if not exists fotos jsonb;

-- id por opcion de sede/modulo (necesario para editar/eliminar una por una desde el panel).
alter table opciones_configurables add column if not exists id bigint generated by default as identity;
create unique index if not exists idx_opciones_configurables_id on opciones_configurables(id);

-- ============================================================================
-- Diccionario de lenguaje inapropiado (Colombia) — 154 terminos
--   groseria_fuerte : se detecta siempre
--   groseria_leve   : solo con sensibilidad "estricto" (la de por defecto)
--   mal_trato       : frases que niegan la atencion o tratan mal al usuario; siempre
-- ============================================================================
insert into lenguaje_inapropiado (termino, categoria) values
    ('hijueputa', 'groseria_fuerte'),
    ('hijueputas', 'groseria_fuerte'),
    ('hijueputica', 'groseria_fuerte'),
    ('jueputa', 'groseria_fuerte'),
    ('hp', 'groseria_fuerte'),
    ('hpta', 'groseria_fuerte'),
    ('hptas', 'groseria_fuerte'),
    ('hijo de puta', 'groseria_fuerte'),
    ('hijos de puta', 'groseria_fuerte'),
    ('hija de puta', 'groseria_fuerte'),
    ('hijuemadre', 'groseria_fuerte'),
    ('gonorrea', 'groseria_fuerte'),
    ('gonorreas', 'groseria_fuerte'),
    ('gonorriento', 'groseria_fuerte'),
    ('gonorrienta', 'groseria_fuerte'),
    ('gonorrio', 'groseria_fuerte'),
    ('malparido', 'groseria_fuerte'),
    ('malparida', 'groseria_fuerte'),
    ('malparidos', 'groseria_fuerte'),
    ('malparidas', 'groseria_fuerte'),
    ('malnacido', 'groseria_fuerte'),
    ('malnacida', 'groseria_fuerte'),
    ('carechimba', 'groseria_fuerte'),
    ('careverga', 'groseria_fuerte'),
    ('carepicha', 'groseria_fuerte'),
    ('culicagado', 'groseria_fuerte'),
    ('culicagada', 'groseria_fuerte'),
    ('pirobo', 'groseria_fuerte'),
    ('piroba', 'groseria_fuerte'),
    ('pirobos', 'groseria_fuerte'),
    ('me vale verga', 'groseria_fuerte'),
    ('vale verga', 'groseria_fuerte'),
    ('puta', 'groseria_fuerte'),
    ('putas', 'groseria_fuerte'),
    ('puto', 'groseria_fuerte'),
    ('putos', 'groseria_fuerte'),
    ('mierda', 'groseria_fuerte'),
    ('mierdas', 'groseria_fuerte'),
    ('comemierda', 'groseria_fuerte'),
    ('come mierda', 'groseria_fuerte'),
    ('verga', 'groseria_fuerte'),
    ('vergas', 'groseria_fuerte'),
    ('coño', 'groseria_fuerte'),
    ('cabron', 'groseria_fuerte'),
    ('cabrona', 'groseria_fuerte'),
    ('cabrones', 'groseria_fuerte'),
    ('culo', 'groseria_fuerte'),
    ('culero', 'groseria_fuerte'),
    ('zorra', 'groseria_fuerte'),
    ('perra', 'groseria_fuerte'),
    ('maricon', 'groseria_fuerte'),
    ('maricona', 'groseria_fuerte'),
    ('maricones', 'groseria_fuerte'),
    ('chupamela', 'groseria_fuerte'),
    ('chupala', 'groseria_fuerte'),
    ('mamaguevo', 'groseria_fuerte'),
    ('mamaguevos', 'groseria_fuerte'),
    ('hijo de perra', 'groseria_fuerte'),
    ('vete a la mierda', 'groseria_fuerte'),
    ('vayase a la mierda', 'groseria_fuerte'),
    ('que se joda', 'groseria_fuerte'),
    ('jodase', 'groseria_fuerte'),
    ('marica', 'groseria_leve'),
    ('maricas', 'groseria_leve'),
    ('guevon', 'groseria_leve'),
    ('guevona', 'groseria_leve'),
    ('huevon', 'groseria_leve'),
    ('huevona', 'groseria_leve'),
    ('gueva', 'groseria_leve'),
    ('guevas', 'groseria_leve'),
    ('idiota', 'groseria_leve'),
    ('idiotas', 'groseria_leve'),
    ('imbecil', 'groseria_leve'),
    ('imbeciles', 'groseria_leve'),
    ('estupido', 'groseria_leve'),
    ('estupida', 'groseria_leve'),
    ('estupidos', 'groseria_leve'),
    ('pendejo', 'groseria_leve'),
    ('pendeja', 'groseria_leve'),
    ('pendejos', 'groseria_leve'),
    ('pendejada', 'groseria_leve'),
    ('bobo', 'groseria_leve'),
    ('boba', 'groseria_leve'),
    ('bobos', 'groseria_leve'),
    ('tarado', 'groseria_leve'),
    ('tarada', 'groseria_leve'),
    ('bruto', 'groseria_leve'),
    ('bruta', 'groseria_leve'),
    ('brutos', 'groseria_leve'),
    ('baboso', 'groseria_leve'),
    ('babosa', 'groseria_leve'),
    ('lambon', 'groseria_leve'),
    ('lambona', 'groseria_leve'),
    ('chandoso', 'groseria_leve'),
    ('chandosa', 'groseria_leve'),
    ('ñero', 'groseria_leve'),
    ('ñera', 'groseria_leve'),
    ('gamin', 'groseria_leve'),
    ('gamina', 'groseria_leve'),
    ('mamon', 'groseria_leve'),
    ('mamona', 'groseria_leve'),
    ('maldito', 'groseria_leve'),
    ('maldita', 'groseria_leve'),
    ('malditos', 'groseria_leve'),
    ('carajo', 'groseria_leve'),
    ('joder', 'groseria_leve'),
    ('jodido', 'groseria_leve'),
    ('jodida', 'groseria_leve'),
    ('no joda', 'groseria_leve'),
    ('inutil', 'groseria_leve'),
    ('inutiles', 'groseria_leve'),
    ('incompetente', 'groseria_leve'),
    ('ignorante', 'groseria_leve'),
    ('no lo puedo ayudar', 'mal_trato'),
    ('no la puedo ayudar', 'mal_trato'),
    ('no los puedo ayudar', 'mal_trato'),
    ('no lo puedo ayudar con su solicitud', 'mal_trato'),
    ('no la puedo ayudar con su solicitud', 'mal_trato'),
    ('no puedo ayudarlo', 'mal_trato'),
    ('no puedo ayudarla', 'mal_trato'),
    ('no puedo hacer nada por usted', 'mal_trato'),
    ('no puedo hacer nada por ti', 'mal_trato'),
    ('averigue en otro lado', 'mal_trato'),
    ('averigue en otra parte', 'mal_trato'),
    ('vaya a averiguar en otro lado', 'mal_trato'),
    ('pregunte en otro lado', 'mal_trato'),
    ('busque a otro', 'mal_trato'),
    ('no me pregunte eso', 'mal_trato'),
    ('no me pregunte a mi', 'mal_trato'),
    ('eso no es conmigo', 'mal_trato'),
    ('eso no es mi problema', 'mal_trato'),
    ('no es mi problema', 'mal_trato'),
    ('ese no es mi problema', 'mal_trato'),
    ('no es mi trabajo', 'mal_trato'),
    ('no es asunto mio', 'mal_trato'),
    ('eso no me compete', 'mal_trato'),
    ('eso no me corresponde', 'mal_trato'),
    ('yo no tengo la culpa', 'mal_trato'),
    ('a mi que me importa', 'mal_trato'),
    ('no me interesa su problema', 'mal_trato'),
    ('arreglese como pueda', 'mal_trato'),
    ('arreglatelas como puedas', 'mal_trato'),
    ('hagale como quiera', 'mal_trato'),
    ('haga lo que quiera', 'mal_trato'),
    ('resuelva usted mismo', 'mal_trato'),
    ('resuelvalo usted', 'mal_trato'),
    ('no tengo tiempo para esto', 'mal_trato'),
    ('no tengo tiempo para usted', 'mal_trato'),
    ('deje de molestar', 'mal_trato'),
    ('no me moleste', 'mal_trato'),
    ('no vuelva a molestarme', 'mal_trato'),
    ('que fastidio con usted', 'mal_trato'),
    ('usted no entiende nada', 'mal_trato'),
    ('no le puedo dar esa informacion', 'mal_trato')
on conflict (termino) do nothing;





