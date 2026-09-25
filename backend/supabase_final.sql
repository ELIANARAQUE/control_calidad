-- ============================================================================
-- Script FINAL para Supabase (correr una sola vez en SQL Editor -> New query).
--
-- 1) Agrega lo nuevo del esquema (3 fotos de registro y tabla de emociones).
-- 2) LIMPIA todas las tablas con datos de prueba, EXCEPTO `super_admin`.
-- 3) Vuelve a cargar los catalogos (tipos de documento, sede/modulo): son listas que
--    necesitan los formularios; se borran y se recargan limpias, no quedan vacias.
--
-- Seguro de correr aunque ya hayas corrido supabase_schema.sql antes.
-- ============================================================================

create extension if not exists pgcrypto;

-- ---------- 1) Cambios de esquema ----------

-- Las 3 fotos del registro (frontal, lateral izquierda, lateral derecha).
alter table usuarios add column if not exists fotos jsonb;

-- Emocion dominante de cada empleado, muestreada cada ~10 s durante el monitoreo
-- (el panel de admin la ve en vivo y el reporte Excel la resume por trabajador).
create table if not exists emociones (
    id bigserial primary key,
    estacion_id text not null,
    emocion text not null,
    probabilidad real,
    "timestamp" timestamptz not null default now()
);
create index if not exists idx_emociones_estacion on emociones(estacion_id);
create index if not exists idx_emociones_timestamp on emociones("timestamp");

-- ---------- 2) Limpieza (todo menos super_admin) ----------

truncate table
    emociones,
    alertas,
    transcripciones,
    eventos_conexion,
    usuarios,
    opciones_configurables
restart identity cascade;

-- tipos_documento es referenciada por usuarios: se vacia despues (usuarios ya esta vacia).
truncate table tipos_documento restart identity cascade;

-- Las fotos de registro viejas (Storage) no se pueden borrar por SQL -Supabase lo bloquea-:
-- vaciarlas desde el dashboard: Storage -> fotos-empleados -> seleccionar todo -> Delete.

-- ---------- 3) Catalogos (desde aqui los administra el panel, no el codigo) ----------

insert into tipos_documento (nombre) values
    ('Cédula de ciudadanía'),
    ('Cédula de extranjería'),
    ('Tarjeta de identidad'),
    ('Pasaporte');

insert into opciones_configurables (tipo, valor, orden) values
    ('sede', 'Sede Principal', 0),
    ('sede', 'Campus Norte', 1),
    ('sede', 'Atención Virtual', 2),
    ('modulo', 'Admisiones y Registro', 0),
    ('modulo', 'Soporte Técnico', 1),
    ('modulo', 'Financiera', 2);

-- super_admin NO se toca: la clave "SAdmin123" (hasheada) sigue igual.
