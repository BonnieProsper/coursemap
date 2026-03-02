from coursemap.domain.seed_data import load_massey_bachelor
from coursemap.services.planner_service import PlannerService


def main():
    config = load_massey_bachelor()
    service = PlannerService(config)

    plan = service.generate_best_plan(
        major="Computer Science"
    )

    print(plan)


if __name__ == "__main__":
    main()