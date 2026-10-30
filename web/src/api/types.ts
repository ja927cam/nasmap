export type Role = 'admin' | 'editor' | 'viewer';
export type Visibility = 'private' | 'organisation' | 'public';
export type GeometryType = 'point' | 'line' | 'polygon' | 'geometry' | 'raster' | 'table';
export type SourceType = 'upload' | 'url' | 'tessera' | 'osm' | 'api' | 'manual';

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: Role;
  is_active: boolean;
  osm_username?: string | null;
  created_at: string;
}

export interface AuthSession {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface LayerStyle {
  color?: string;
  fillColor?: string;
  fillOpacity?: number;
  lineWidth?: number;
  opacity?: number;
  circleRadius?: number;
  bands?: number[];
}

export interface Layer {
  id: string;
  owner_id: string;
  name: string;
  description: string;
  visibility: Visibility;
  geometry_type: GeometryType;
  source_type: SourceType;
  style: LayerStyle;
  metadata: Record<string, any>;
  attribution: string;
  licence: string;
  feature_count: number;
  access_role?: 'owner' | 'editor' | 'viewer' | null;
  created_at: string;
  updated_at: string;
  owner?: User;
}

export interface GeoFeature {
  type: 'Feature';
  id: string;
  geometry: any;
  properties: Record<string, any>;
  version?: number;
  updated_at?: string;
  created_at?: string;
}

export interface FeatureCollection {
  type: 'FeatureCollection';
  features: GeoFeature[];
  meta: { total: number; limit?: number; offset?: number; returned: number };
}

export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface ImportJob {
  id: string;
  job_type: 'upload' | 'url' | 'tessera' | 'raster' | 'osm' | 'export' | 'ingest';
  status: JobStatus;
  progress: number;
  message: string;
  error?: string | null;
  layer_id?: string | null;
  source_url?: string | null;
  options: Record<string, any>;
  result: Record<string, any>;
  attempts: number;
  cancel_requested: boolean;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at: string;
  layer?: { id: string; name: string; geometry_type: string };
  coverage?: { tile_count: number; variant: string; max_tiles: number };
}

export interface PublicConfig {
  app_name: string;
  basemap_mode: 'remote_osm' | 'local';
  osm_tile_url: string;
  osm_tile_attribution: string;
  tileserver_public_url: string;
  registration_enabled: boolean;
  osm_oauth_enabled: boolean;
  tessera_enabled: boolean;
  max_upload_mb: number;
  max_photo_mb: number;
  max_attachment_mb: number;
  max_url_import_mb: number;
}

export interface TesseraCoverage {
  bbox: number[];
  year: number;
  variant: string;
  version: string;
  tile_count: number;
  tiles: { id: string; year: number; lon: number; lat: number; bbox: number[] }[];
  available_years: number[];
  available_variants: string[];
  max_tiles: number;
  crs: string;
  resolution: string;
  band_count: number;
  licence: string;
  attribution: string;
  coverage_within_limit: boolean;
}

export interface PageMeta {
  total: number;
  limit: number;
  offset: number;
  returned: number;
}

export interface Paged<T> {
  items: T[];
  meta: PageMeta;
}


export interface Attachment {
  id: string;
  feature_id: string | null;
  layer_id: string | null;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
  content_url: string;
  thumb_url: string;
}

export interface PhotoImportResult {
  layer_id: string | null;
  layer_name?: string;
  created_features: number;
  attached_photos: number;
  skipped: { filename: string; reason: string }[];
  attachments?: Attachment[];
  message?: string;
}
