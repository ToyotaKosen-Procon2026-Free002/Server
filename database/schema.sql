-- 作り直しコマンド
-- sudo -u postgres psql -d coco_seal_db -c "DROP SCHEMA public CASCADE;CREATE SCHEMA public;GRANT ALL ON SCHEMA public TO coco_seal_user;ALTER SCHEMA public OWNER TO coco_seal_user;CREATE EXTENSION IF NOT EXISTS postgis;" && psql -U coco_seal_user -d coco_seal_db -f ./database/schema.sql -h localhost

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
    order INT NOT NULL DEFAULT 0,

    CONSTRAINT seals_rarity
        FOREIGN KEY (rarity)
        REFERENCES seal_rarities(id)
);


INSERT INTO seals (name, description, rarity, image_path, "order") VALUES
("うさぎ", "大きな耳と広い視野で敵をいち早く察知できるよ", 0, "seals/usagi.png", 1),
("ねむねむうさぎ", "寝ている時は鼻のヒクヒクがとまるよ", 0, "seals/nemunemu_usagi.png", 2),
("ひょっこりうさぎ", "大きな耳は温度調節にも使われてるよ", 1, "seals/hyokkori_usagi.png", 3),
("にんじんうさぎ", "ここだけの話、本当に好きな食べ物は葉っぱだよ", 1, "seals/ninzin_usagi.png", 4),
("しば", "柴犬は国の天然記念物にも指定されてるよ", 0, "seals/siba.png", 5),
("ふせしば", "オオカミに最も近い犬種って言われてるよ", 0, "seals/fuse_siba.png", 6),
("ぴょんしば", "柴犬はツンデレだよ", 1, "seals/pyon_siba.png", 7),
("すやしば", "急所であるお腹を隠して眠っているよ", 1, "seals/suya_siba.png", 8),
("ねこ", "1日のうち12時間〜16時間を睡眠に使うよ", 0, "seals/neko.png", 9),
("ぴょんねこ", "ジャンプ力は身長の約5倍だよ", 0, "seals/pyon_neko.png", 10),
("のびねこ", "おヒゲはセンサーだよ", 1, "seals/nobi_neko.png", 11),
("ねむねこ", "本気で走るとウサイン・ボルト選手よりも速いよ！", 1, "seals/nemu_neko.png", 12),
("パンダ", "生まれたばかりの赤ちゃんは100〜150gくらいしかないよ", 0, "seals/panda.png", 13),
("たけのこぱんだ", "実は竹よりたけのこの方が栄養が高くておきにいり！", 0, "seals/takenoko_panda.png", 14),
("ハートぱんだ", "パンダのうんちは全く臭くないよ！", 1, "seals/heart_panda.png", 15),
("ささぱんだ", "手のひらに第6と第7の指があるよ", 1, "seals/sasa_panda.png", 16),
("はむはむ", "前歯が一生伸び続けるよ", 0, "seals/hamuhamu.png", 17),
("はむカップ", "実はねほっぺがお尻まで伸びるよ", 0, "seals/hamu_kappu.png", 18),
("ラッキーはむはむ", "ハムスターには世界がモノクロに見えてるよ", 1, "seals/rakki-_hamuhamu.png", 19),
("はむはむスター", "超がつくほどの一匹狼。１ケージに１匹が鉄則だよ", 1, "seals/hamuhamu_star.png", 20),
("ハート", "赤色のハートの意味は愛してるだよ", 0, "seals/heart.png", 21),
("雲", "大きな雲は実は重いよ", 0, "seals/kumo.png", 22),
("チューリップ", "花言葉は思いやりだよ", 0, "seals/tyu-rippu.png", 23),
("リボン", "ピンク色のりぼんだよ", 0, "seals/ribonn.png", 24),
("スター", "一番熱い星は青色だよ！", 0, "seals/star.png", 25),
("トリケラトプス", "何百本もの歯をもってるよ", 1, "seals/torikeratopusu.png", 26);



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