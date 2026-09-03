"""Refresh and populate all reference marks for case drawings in PatentEvidence."""
import json
import psycopg

DATABASE_URL = "postgresql://patent_evidence_migration:migration-dev-only@127.0.0.1:5435/patent_evidence"

FIG_MARKS = {
    "图 2": [
        {"mark": "10", "name": "机器人臂组件"},
        {"mark": "12", "name": "前臂"},
        {"mark": "14", "name": "手"},
        {"mark": "18", "name": "中心线"},
        {"mark": "100", "name": "关节组件"},
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
        {"mark": "12", "name": "前臂"},
        {"mark": "14", "name": "手"},
        {"mark": "16", "name": "手指"},
        {"mark": "18", "name": "中心线"},
        {"mark": "100", "name": "关节组件"},
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
        {"mark": "12", "name": "前臂"},
        {"mark": "14", "name": "手"},
        {"mark": "16", "name": "手指"},
        {"mark": "100", "name": "关节组件"},
        {"mark": "102", "name": "偏转轴线"},
        {"mark": "104", "name": "俯仰轴线"},
        {"mark": "118", "name": "万向节"},
        {"mark": "120", "name": "手结构"},
    ],
    "图 3": [
        {"mark": "10", "name": "机器人臂组件"},
        {"mark": "12", "name": "前臂"},
        {"mark": "14", "name": "手"},
        {"mark": "16", "name": "手指"},
        {"mark": "100", "name": "关节组件"},
        {"mark": "114", "name": "连杆"},
        {"mark": "116", "name": "致动器"},
        {"mark": "118", "name": "万向节"},
        {"mark": "120", "name": "手结构"},
        {"mark": "150", "name": "手指构件"},
        {"mark": "174", "name": "控制线缆"},
    ],
    "图 4": [
        {"mark": "10", "name": "机器人臂组件"},
        {"mark": "14", "name": "手"},
        {"mark": "16", "name": "手指"},
        {"mark": "174", "name": "控制线缆"},
        {"mark": "178", "name": "线缆引导结构"},
        {"mark": "182", "name": "引导通道"},
        {"mark": "186", "name": "引导侧"},
        {"mark": "190", "name": "线缆引导构件"},
        {"mark": "218", "name": "线缆组218"},
        {"mark": "222", "name": "控制线缆通道"},
        {"mark": "226", "name": "终端布线结构"},
    ],
    "图 5": [
        {"mark": "100", "name": "关节组件"},
        {"mark": "118", "name": "万向节"},
        {"mark": "120", "name": "手结构"},
        {"mark": "174", "name": "控制线缆"},
        {"mark": "178", "name": "线缆引导结构"},
        {"mark": "218", "name": "线缆组218"},
        {"mark": "222", "name": "控制线缆通道"},
        {"mark": "226", "name": "终端布线结构"},
    ],
    "图 6": [
        {"mark": "16", "name": "手指"},
        {"mark": "150", "name": "手指构件"},
        {"mark": "152", "name": "轴线"},
        {"mark": "154", "name": "顶表面"},
        {"mark": "158", "name": "底表面"},
        {"mark": "162", "name": "抓握表面"},
        {"mark": "166", "name": "接触表面"},
        {"mark": "170", "name": "指关节"},
        {"mark": "174", "name": "控制线缆"},
    ],
    "图 7": [
        {"mark": "16", "name": "手指"},
        {"mark": "150", "name": "手指构件"},
        {"mark": "152", "name": "轴线"},
        {"mark": "162", "name": "抓握表面"},
        {"mark": "166", "name": "接触表面"},
        {"mark": "170", "name": "指关节"},
        {"mark": "174", "name": "控制线缆"},
    ],
    "图 8": [
        {"mark": "16", "name": "手指"},
        {"mark": "150", "name": "手指构件"},
        {"mark": "152", "name": "轴线"},
        {"mark": "154", "name": "顶表面"},
        {"mark": "158", "name": "底表面"},
        {"mark": "162", "name": "抓握表面"},
        {"mark": "166", "name": "接触表面"},
        {"mark": "170", "name": "指关节"},
        {"mark": "174", "name": "控制线缆"},
    ],
}


def main():
    conn = psycopg.connect(DATABASE_URL)
    with conn.cursor() as cur:
        for fig_label, marks in FIG_MARKS.items():
            cur.execute(
                """UPDATE case_drawings
                SET reference_marks = %s
                WHERE figure_label = %s""",
                (json.dumps(marks), fig_label),
            )
            print(f"Updated {fig_label}: {len(marks)} reference marks mapped.")
        conn.commit()
    conn.close()
    print("All drawing reference marks successfully refreshed!")


if __name__ == "__main__":
    main()
