"""Refresh and populate exact, visually verified reference marks and claims annotations in PatentEvidence."""
import json
import psycopg

DATABASE_URL = "postgresql://patent_evidence_migration:migration-dev-only@127.0.0.1:5435/patent_evidence"

# Set of marks explicitly/implicitly defined in patent claims
CLAIM_MARKS = {
    "10": False,
    "12": True,   # 权利要求 1: 前臂构件
    "14": True,   # 权利要求 1: 手构件
    "16": True,   # 权利要求 1: 附肢构件
    "18": False,
    "100": True,  # 权利要求 1: 腕关节
    "102": True,  # 权利要求 6: 偏转轴线
    "104": True,  # 权利要求 6: 俯仰轴线
    "106": False,
    "106a": False,
    "106b": False,
    "108": False,
    "108a": False,
    "108b": False,
    "110": False,
    "112": False,
    "113a": False,
    "113b": False,
    "114": False,
    "114a": False,
    "114b": False,
    "116": False,
    "116a": False,
    "116b": False,
    "118": False,
    "120": False,
    "122": False,
    "124": False,
    "126": False,
    "128": False,
    "136": False,
    "140": False,
    "142": False,
    "150": True,   # 权利要求 1: 附肢构件结构
    "150A": True,  # 权利要求 12: 第一结构（远侧）
    "150B": True,  # 权利要求 12: 第二结构（中部）
    "150C": True,  # 权利要求 12: 第三结构（中部）
    "150D": True,  # 权利要求 12: 第四结构（基部）
    "152": False,
    "154": False,
    "158": False,
    "162": False,
    "166": True,   # 权利要求 9: 枢轴接触面
    "170": True,   # 权利要求 9, 11: 枢轴关节/第一关节
    "174": True,   # 权利要求 1: 控制线缆
    "178": False,
    "182": True,   # 权利要求 1, 2: 第一构造
    "186": True,   # 权利要求 1: 腕关节前臂侧（第一侧）
    "190": True,   # 权利要求 1, 2: 第二构造
    "194": True,   # 权利要求 1: 腕关节手侧（第二侧）
    "198": True,   # 权利要求 5: 过渡区
    "202": True,   # 权利要求 3, 4: 第一控制线缆支撑构件
    "206": True,   # 权利要求 3, 4: 第二控制线缆支撑构件
    "210": False,
    "214": False,
    "218A": True,  # 权利要求 14: 第一控制线缆组
    "218B": True,  # 权利要求 14: 第二控制线缆组
    "218C": True,  # 权利要求 14: 第三控制线缆组
    "218D": True,  # 权利要求 14: 第四控制线缆组
    "218E": True,  # 权利要求 14: 第五控制线缆组
    "222": True,   # 权利要求 7, 8, 9: 控制线缆通道
    "226": True,   # 权利要求 10: 终端结构
}

FIG_MARKS = {
    "图 4": [
        {"mark": "174", "name": "控制线缆"},
        {"mark": "182", "name": "第一构造"},
        {"mark": "186", "name": "第一侧(前臂侧)"},
        {"mark": "190", "name": "第二构造"},
        {"mark": "194", "name": "第二侧(手侧)"},
        {"mark": "198", "name": "过渡区"},
        {"mark": "218A", "name": "控制线缆第一组"},
        {"mark": "218B", "name": "控制线缆第二组"},
        {"mark": "218C", "name": "控制线缆第三组"},
        {"mark": "218D", "name": "控制线缆第四组"},
        {"mark": "218E", "name": "控制线缆第五组"},
    ],
    "图 2": [
        {"mark": "10", "name": "机器人臂组件"},
        {"mark": "12", "name": "前臂构件"},
        {"mark": "14", "name": "手构件"},
        {"mark": "18", "name": "中心线"},
        {"mark": "100", "name": "腕关节(关节组件)"},
        {"mark": "102", "name": "偏转轴线"},
        {"mark": "104", "name": "俯仰轴线"},
        {"mark": "106a", "name": "第一轴线106a"},
        {"mark": "106b", "name": "第一轴线106b"},
        {"mark": "108a", "name": "第二轴线108a"},
        {"mark": "108b", "name": "第二轴线108b"},
        {"mark": "110", "name": "前臂框架构件"},
        {"mark": "112", "name": "支架"},
        {"mark": "113a", "name": "上构件113a"},
        {"mark": "114a", "name": "第一连杆114a"},
        {"mark": "114b", "name": "第二连杆114b"},
        {"mark": "116a", "name": "第一致动器116a"},
        {"mark": "116b", "name": "第二致动器116b"},
        {"mark": "118", "name": "万向节"},
        {"mark": "120", "name": "手结构"},
        {"mark": "122", "name": "耦接万向节"},
        {"mark": "124", "name": "通道"},
        {"mark": "128", "name": "远端"},
        {"mark": "136", "name": "偏移距离"},
        {"mark": "140", "name": "第一侧"},
        {"mark": "142", "name": "第二侧"},
        {"mark": "174", "name": "控制线缆"},
    ],
    "图 1": [
        {"mark": "10", "name": "机器人臂组件"},
        {"mark": "12", "name": "前臂构件"},
        {"mark": "14", "name": "手构件"},
        {"mark": "16", "name": "附肢构件(手指)"},
        {"mark": "18", "name": "中心线"},
        {"mark": "100", "name": "腕关节(关节组件)"},
        {"mark": "102", "name": "偏转轴线"},
        {"mark": "104", "name": "俯仰轴线"},
        {"mark": "106", "name": "第一轴线"},
        {"mark": "108", "name": "第二轴线"},
        {"mark": "110", "name": "前臂框架构件"},
        {"mark": "112", "name": "支架"},
        {"mark": "113a", "name": "上构件113a"},
        {"mark": "113b", "name": "下构件113b"},
        {"mark": "114", "name": "连杆"},
        {"mark": "116", "name": "致动器"},
        {"mark": "118", "name": "万向节"},
        {"mark": "120", "name": "手结构"},
        {"mark": "122", "name": "耦接万向节"},
        {"mark": "126", "name": "近端"},
        {"mark": "128", "name": "远端"},
        {"mark": "174", "name": "控制线缆"},
    ],
    "摘要附图": [
        {"mark": "10", "name": "机器人臂组件"},
        {"mark": "12", "name": "前臂构件"},
        {"mark": "14", "name": "手构件"},
        {"mark": "16", "name": "附肢构件(手指)"},
        {"mark": "100", "name": "腕关节(关节组件)"},
        {"mark": "102", "name": "偏转轴线"},
        {"mark": "104", "name": "俯仰轴线"},
        {"mark": "118", "name": "万向节"},
        {"mark": "120", "name": "手结构"},
    ],
    "图 3": [
        {"mark": "10", "name": "机器人臂组件"},
        {"mark": "12", "name": "前臂构件"},
        {"mark": "14", "name": "手构件"},
        {"mark": "16", "name": "附肢构件(手指)"},
        {"mark": "100", "name": "腕关节(关节组件)"},
        {"mark": "114", "name": "连杆"},
        {"mark": "116", "name": "致动器"},
        {"mark": "118", "name": "万向节"},
        {"mark": "120", "name": "手结构"},
        {"mark": "150", "name": "附肢手指构件"},
        {"mark": "150A", "name": "远侧第一结构(150A)"},
        {"mark": "150B", "name": "中部第二结构(150B)"},
        {"mark": "150C", "name": "中部第三结构(150C)"},
        {"mark": "150D", "name": "基部第四结构(150D)"},
        {"mark": "174", "name": "控制线缆"},
        {"mark": "178", "name": "线缆引导结构"},
    ],
    "图 5": [
        {"mark": "100", "name": "腕关节(关节组件)"},
        {"mark": "118", "name": "万向节"},
        {"mark": "120", "name": "手结构"},
        {"mark": "174", "name": "控制线缆"},
        {"mark": "182", "name": "第一构造"},
        {"mark": "186", "name": "第一侧(前臂侧)"},
        {"mark": "190", "name": "第二构造"},
        {"mark": "194", "name": "第二侧(手侧)"},
        {"mark": "198", "name": "过渡区"},
        {"mark": "202", "name": "第一控制线缆支撑构件"},
        {"mark": "206", "name": "第二控制线缆支撑构件"},
        {"mark": "210", "name": "紧固件"},
        {"mark": "214", "name": "支撑面"},
    ],
    "图 6": [
        {"mark": "16", "name": "附肢构件(手指)"},
        {"mark": "150A", "name": "远侧第一结构(150A)"},
        {"mark": "150B", "name": "中部第二结构(150B)"},
        {"mark": "150C", "name": "中部第三结构(150C)"},
        {"mark": "150D", "name": "基部第四结构(150D)"},
        {"mark": "152", "name": "轴线"},
        {"mark": "166", "name": "滚动接触表面"},
        {"mark": "170", "name": "枢轴关节(指关节)"},
        {"mark": "174", "name": "控制线缆"},
        {"mark": "222", "name": "控制线缆通道"},
    ],
    "图 7": [
        {"mark": "16", "name": "附肢构件(手指)"},
        {"mark": "150A", "name": "远侧第一结构(150A)"},
        {"mark": "150B", "name": "中部第二结构(150B)"},
        {"mark": "150C", "name": "中部第三结构(150C)"},
        {"mark": "150D", "name": "基部第四结构(150D)"},
        {"mark": "152", "name": "轴线"},
        {"mark": "162", "name": "抓握方向"},
        {"mark": "170", "name": "枢轴关节(指关节)"},
        {"mark": "174", "name": "控制线缆"},
        {"mark": "222", "name": "控制线缆通道"},
        {"mark": "226", "name": "终端结构"},
    ],
    "图 8": [
        {"mark": "16", "name": "附肢构件(手指)"},
        {"mark": "150A", "name": "远侧第一结构(150A)"},
        {"mark": "150B", "name": "中部第二结构(150B)"},
        {"mark": "150C", "name": "中部第三结构(150C)"},
        {"mark": "150D", "name": "基部第四结构(150D)"},
        {"mark": "152", "name": "轴线"},
        {"mark": "154", "name": "顶表面"},
        {"mark": "158", "name": "底表面"},
        {"mark": "162", "name": "抓握表面"},
        {"mark": "166", "name": "滚动接触表面"},
        {"mark": "170", "name": "枢轴关节(指关节)"},
        {"mark": "174", "name": "控制线缆"},
        {"mark": "226", "name": "终端结构"},
    ],
}


def main():
    conn = psycopg.connect(DATABASE_URL)
    with conn.cursor() as cur:
        for fig_label, marks in FIG_MARKS.items():
            enriched_marks = []
            for m in marks:
                mk = m["mark"]
                is_claim = CLAIM_MARKS.get(mk, False)
                enriched_marks.append({
                    "mark": mk,
                    "name": m["name"],
                    "is_claim_feature": is_claim,
                })
            cur.execute(
                """UPDATE case_drawings
                SET reference_marks = %s
                WHERE figure_label = %s""",
                (json.dumps(enriched_marks), fig_label),
            )
            claim_count = sum(1 for item in enriched_marks if item["is_claim_feature"])
            print(f"Updated {fig_label}: {len(enriched_marks)} marks ({claim_count} claim features).")
        conn.commit()
    conn.close()
    print("All drawing reference marks successfully updated with claims integration!")


if __name__ == "__main__":
    main()
