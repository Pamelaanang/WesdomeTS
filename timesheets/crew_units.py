"""Rules for crew groups and what each unit runs. Every write from the
Superintendent's screens goes through these checks before it's saved."""

from users.models import BasketLead, CrewAssignment, User

from .models import CrewGroup, CrewGroupMember, Crews, UnitDiscipline


def single_crews():
    """Single crews (A, B, C, ...) in column order. Joint rows are excluded."""
    return [c for c in Crews.objects.filter(isactive=1).order_by('crewname') if len(c.crewname) == 1]


def _group_members(group):
    return {m.crew for m in CrewGroupMember.objects.filter(group=group).select_related('crew')}


def _groups_running(crew, discipline, exclude_group=None):
    """Other groups that contain this crew and already run this discipline."""
    links = UnitDiscipline.objects.filter(
        discipline=discipline, group__members__crew=crew,
    ).exclude(group=exclude_group).select_related('group')
    return [link.group.groupname for link in links]


def membership_error(group, crew):
    """Why this crew can't join this group, or None if it can."""
    if len(crew.crewname) != 1:
        return f'{crew.crewname} is a joint crew, not a single crew, so it can\'t join a group.'
    members = _group_members(group)
    if crew in members:
        return f'Crew {crew.crewname} is already in {group.groupname}.'

    names = sorted([m.crewname for m in members] + [crew.crewname])
    order = [c.crewname for c in single_crews()]
    positions = sorted(order.index(n) for n in names)
    if positions != list(range(positions[0], positions[-1] + 1)):
        return (f'{group.groupname} needs crews that sit next to each other on the grid. '
                f'Crew {crew.crewname} would leave a gap.')

    for link in UnitDiscipline.objects.filter(group=group).select_related('discipline'):
        clash = _groups_running(crew, link.discipline, exclude_group=group)
        if clash:
            return (f'Crew {crew.crewname} already runs {link.discipline.name} in '
                    f'{", ".join(clash)}. A crew can run a discipline in one group only.')
    return None


def unit_discipline_error(unit, discipline):
    """Why this unit can't run this discipline, or None if it can."""
    if isinstance(unit, CrewGroup):
        for member in _group_members(unit):
            clash = _groups_running(member, discipline, exclude_group=unit)
            if clash:
                return (f'Crew {member.crewname} already runs {discipline.name} in '
                        f'{", ".join(clash)}. A crew can run a discipline in one group only.')
    return None


def discipline_removal_blockers(link):
    """People still working in this unit's basket. Empty means it can be removed."""
    unit_name = link.unit_name
    people = []
    for a in CrewAssignment.objects.filter(
        enddate__isnull=True, crewid__crewname=unit_name, discipline=link.discipline,
    ).select_related('employee'):
        people.append(f'{a.employee.firstname} {a.employee.lastname}')
    for s in User.objects.filter(
        isactive=True, crewid__crewname=unit_name, discipline=link.discipline,
    ):
        people.append(f'{s.firstname} {s.lastname} (shifter)')
    for b in BasketLead.objects.filter(
        enddate__isnull=True, crewid__crewname=unit_name, discipline=link.discipline,
    ).select_related('shifter'):
        people.append(f'{b.shifter.firstname} {b.shifter.lastname} (shifter)')
    return people


def also_covers_error(primary, target):
    """Why this basket can't be the 'also covers' basket for a seat, or None if it can.
    Whether a crew may cover a discipline comes from the unit links: the target basket
    only exists if its crew runs that discipline, so no crew-type rule is needed here."""
    if target is None:
        return None
    if primary is None:
        return 'A seat needs a primary basket before it can also cover another.'
    if target.pk == primary.pk:
        return 'A seat can\'t also cover the basket it already belongs to.'
    if target.discipline_id != primary.discipline_id:
        return f'The also-covers basket must run {primary.discipline.name}.'
    return None
