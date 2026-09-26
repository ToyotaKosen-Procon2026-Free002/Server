-- 作り直しコマンド
-- sudo -u postgres psql -d coco_seal_db -c "DROP SCHEMA public CASCADE;CREATE SCHEMA public;GRANT ALL ON SCHEMA public TO coco_seal_user;ALTER SCHEMA public OWNER TO coco_seal_user;CREATE EXTENSION IF NOT EXISTS postgis;"
-- psql -U coco_seal_user -d coco_seal_db -f ./database/schema.sql -h localhost

-- 全部確認コマンド
-- psql -U coco_seal_user -d coco_seal_db -h localhost


-- シール

CREATE TABLE seal_rarities (
    id SMALLINT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
INSERT INTO seal_rarities VALUES (0, 'N'), (1, 'R'), (2, 'O');

CREATE TABLE seals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    rarity SMALLINT NOT NULL,
    image_path TEXT NOT NULL,

    CONSTRAINT seals_rarity
        FOREIGN KEY (rarity)
        REFERENCES seal_rarities(id)
);


CREATE TABLE seal_packs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    once_price SMALLINT NOT NULL,
    image_path TEXT NOT NULL,
    is_opened BOOLEAN NOT NULL
);

CREATE TABLE seal_packs_root_tables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seal_pack_id UUID NOT NULL,
    seal_id UUID NOT NULL,
    weight DOUBLE PRECISION NOT NULL,

    CONSTRAINT root_table_seal_pack_id
        FOREIGN KEY (seal_pack_id)
        REFERENCES seal_packs(id)
        ON DELETE CASCADE,

    CONSTRAINT root_table_seal_pack_id
        FOREIGN KEY (seal_id)
        REFERENCES seals(id)
);



-- ユーザー

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firebase_uid TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    display_name TEXT NOT NULL,
    roll SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE user_notify_token (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    notify_token TEXT NOT NULL UNIQUE,

    CONSTRAINT notify_user
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);



-- 子機

CREATE TABLE devices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_key BYTEA NOT NULL,

    user_id UUID NULL,
    name TEXT NOT NULL,
    coins INTEGER NOT NULL DEFAULT 0,
    battery DOUBLE PRECISION NOT NULL DEFAULT 50,

    last_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT devices_user
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE,
    
    CONSTRAINT devices_coins_positive
        CHECK (coins >= 0)
);

CREATE TABLE seal_statuses (
    id SMALLINT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
INSERT INTO seal_statuses VALUES (0, 'OWNED'), (1, 'BOOK'), (2, 'TRADING');

CREATE TABLE device_seals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID NOT NULL,
    seal_id UUID NOT NULL,
    status_id SMALLINT NOT NULL DEFAULT 0,
    book_page SMALLINT NULL,
    book_x DOUBLE PRECISION NULL,
    book_y DOUBLE PRECISION NULL,
    book_rotation DOUBLE PRECISION NULL,
    book_scale DOUBLE PRECISION NULL,

    CONSTRAINT device_seals_status
        FOREIGN KEY (status_id)
        REFERENCES seal_statuses(id),
    
    CONSTRAINT device_seals_device
        FOREIGN KEY (device_id)
        REFERENCES devices(id)
        ON DELETE CASCADE,

    CONSTRAINT device_seals_seal
        FOREIGN KEY (seal_id)
        REFERENCES seals(id)
        ON DELETE CASCADE,

    CONSTRAINT device_seals_book_position
        CHECK (
            status_id <> 1
            OR (
                book_page IS NOT NULL
                AND book_x IS NOT NULL
                AND book_y IS NOT NULL
            )
        )
);


-- 親機

CREATE TABLE gateways (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_key BYTEA NOT NULL,

    name TEXT NOT NULL,
    location GEOGRAPHY(Point, 4326) NULL,
    distribute_seal_id UUID NULL,
    user_id UUID NULL,

    CONSTRAINT gateways_seal
        FOREIGN KEY (distribute_seal_id)
        REFERENCES seals(id)
        ON DELETE SET NULL,

    CONSTRAINT gateways_user_id
        FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
);



-- すれ違いログ

CREATE TABLE encounters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL UNIQUE,

    device_id UUID NOT NULL,
    opponent_device_id UUID NULL,
    gateway_id UUID NULL,

    detected_at TIMESTAMPTZ NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    send_seal_id UUID NULL,
    receive_seal_id UUID NULL,

    CONSTRAINT encounters_device
        FOREIGN KEY (device_id)
        REFERENCES devices(id)
        ON DELETE CASCADE,
    
    CONSTRAINT encounters_opponent_device
        FOREIGN KEY (opponent_device_id)
        REFERENCES devices(id),
    
    CONSTRAINT encounters_gateway
        FOREIGN KEY (gateway_id)
        REFERENCES gateways(id),
    
    CONSTRAINT encounters_send_seal
        FOREIGN KEY (send_seal_id)
        REFERENCES seals(id),
    
    CONSTRAINT encounters_receive_seal
        FOREIGN KEY (receive_seal_id)
        REFERENCES seals(id),

    CONSTRAINT encounters_target_check
        CHECK (
            (opponent_device_id IS NOT NULL AND gateway_id IS NULL)
            OR
            (opponent_device_id IS NULL AND gateway_id IS NOT NULL)
        )
);


-- SOSログ

CREATE TABLE sos_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL UNIQUE,

    device_id UUID NOT NULL,
    sos_at TIMESTAMPTZ NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    notified BOOLEAN NOT NULL DEFAULT FALSE,

    CONSTRAINT sos_events_device
        FOREIGN KEY (device_id)
        REFERENCES devices(id)
);

CREATE TABLE sos_receivers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    sos_id UUID NOT NULL,
    gateway_id UUID NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,

    CONSTRAINT sos_receivers_sos
        FOREIGN KEY (sos_id)
        REFERENCES sos_events(id)
        ON DELETE CASCADE,
    
    CONSTRAINT sos_receivers_gateway
        FOREIGN KEY (gateway_id)
        REFERENCES gateways(id)
);


-- ウィークリーミッション

CREATE TABLE weekly_missions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,                  -- 例: 「親機と1回すれ違おう」
    description TEXT NOT NULL,            -- 例: 「街中の親機(Gateway)とすれ違い通信を行う」
    target_type TEXT NOT NULL,            -- 例: 'ENCOUNTER_GATEWAY', 'GET_SEAL', 'SOS_HELP' 等
    target_value INTEGER NOT NULL,        -- 達成に必要な回数 (例: 1, 3, 5)
    reward_coins INTEGER NOT NULL DEFAULT 0, -- 報酬コイン数
    is_active BOOLEAN NOT NULL DEFAULT TRUE  -- 現在採用されているミッションか
);

CREATE TABLE device_mission_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id UUID NOT NULL,
    mission_id UUID NOT NULL,
    
    -- 週の識別（該当週の「月曜日の日付」を保持するのが最も扱いやすい）
    week_start_date DATE NOT NULL, 
    
    current_value INTEGER NOT NULL DEFAULT 0, -- 現在の達成数 (例: 2 / 3)
    is_completed BOOLEAN NOT NULL DEFAULT FALSE, -- 達成条件を満たしたか
    is_claimed BOOLEAN NOT NULL DEFAULT FALSE,   -- 報酬を受け取ったか
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_progress_device
        FOREIGN KEY (device_id)
        REFERENCES devices(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_progress_mission
        FOREIGN KEY (mission_id)
        REFERENCES weekly_missions(id)
        ON DELETE CASCADE,

    -- 同じデバイス・同じミッション・同じ週で重複レコードを作らない
    CONSTRAINT unique_device_mission_per_week
        UNIQUE (device_id, mission_id, week_start_date)
);


-- インデックス

CREATE INDEX idx_device_seals_device
ON device_seals(device_id);

CREATE INDEX idx_encounters_device
ON encounters(device_id);

CREATE INDEX idx_sos_events_device
ON sos_events(device_id);

CREATE INDEX idx_sos_receivers_sos
ON sos_receivers(sos_id);

CREATE INDEX idx_device_mission_progress_search 
ON device_mission_progress (device_id, week_start_date);