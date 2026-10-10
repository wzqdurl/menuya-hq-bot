-- MenúYa HQ — esquema compartido VM + Railway
-- La empresa vive aquí, no en archivos locales ni memoria volátil.

CREATE TABLE IF NOT EXISTS prospectos (
  id SERIAL PRIMARY KEY,
  negocio TEXT NOT NULL,
  telefono TEXT NOT NULL,
  zona TEXT,
  estado TEXT NOT NULL DEFAULT 'nuevo', -- nuevo, contactado, interesado, cerrado, descartado
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(telefono)
);

CREATE TABLE IF NOT EXISTS acciones (
  id SERIAL PRIMARY KEY,
  tipo TEXT NOT NULL,           -- whatsapp, publicar, etc.
  destino TEXT NOT NULL,
  mensaje TEXT NOT NULL,
  estado TEXT NOT NULL DEFAULT 'pendiente', -- pendiente, aprobada, rechazada, reclamada, enviada, fallida
  creada TIMESTAMPTZ DEFAULT NOW(),
  actualizada TIMESTAMPTZ DEFAULT NOW(),
  resultado TEXT
);

CREATE TABLE IF NOT EXISTS actividad (
  id SERIAL PRIMARY KEY,
  at TIMESTAMPTZ DEFAULT NOW(),
  tipo TEXT NOT NULL,           -- orden_recibida, pensando, trabajando, sintetizando, decision, accion_propuesta, aprobada, rechazada, enviada
  actor TEXT NOT NULL,          -- JEFE, COORDINADORA, VENTAS, etc.
  detalle TEXT
);
CREATE INDEX IF NOT EXISTS idx_actividad_at ON actividad(at DESC);

CREATE TABLE IF NOT EXISTS estado (
  clave TEXT PRIMARY KEY,
  valor TEXT NOT NULL,
  actualizado TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hechos (
  clave TEXT PRIMARY KEY,
  valor TEXT NOT NULL,
  actualizado TIMESTAMPTZ DEFAULT NOW(),
  fuente TEXT
);
CREATE TABLE IF NOT EXISTS agentes_vivo (
  nombre TEXT PRIMARY KEY,
  data JSONB NOT NULL,
  actualizado TIMESTAMPTZ DEFAULT NOW()
);
