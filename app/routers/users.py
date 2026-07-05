from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (
    User,
    Project,
    Organization,
    OrganizationMembership,
    OrganizationRole,
)
from app.schemas import (
    UserCreate,
    Token,
    ProjectCreate,
    ProjectOut,
    OrganizationCreate,
    OrganizationOut,
    PaginatedMeta,
)
from app.auth import get_password_hash, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api/users", tags=["Authentication & Projects"])


# --- User Management Endpoints ---

@router.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(user_in: UserCreate, db: Session = Depends(get_db)):
    """
    Register a brand new user into the database system.
    """
    existing_user = db.query(User).filter(User.email == user_in.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists."
        )

    hashed_password = get_password_hash(user_in.password)
    new_user = User(email=user_in.email, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User registered successfully", "email": new_user.email}


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    """
    Login endpoint compatible with Swagger frontend form and standard OAuth2 specifications.
    """
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect email or password"
        )

    access_token = create_access_token(data={"sub": user.email})
    return {"access_token": access_token, "token_type": "bearer"}


# --- Organization Management Endpoints ---

@router.post("/organizations", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    org_in: OrganizationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create an organization and attach current user as OWNER.
    """
    existing_org = db.query(Organization).filter(Organization.name == org_in.name).first()
    if existing_org:
        raise HTTPException(status_code=400, detail="Organization name already exists")

    org = Organization(name=org_in.name)
    db.add(org)
    db.commit()
    db.refresh(org)

    owner_membership = OrganizationMembership(
        organization_id=org.id,
        user_id=current_user.id,
        role=OrganizationRole.OWNER,
    )
    db.add(owner_membership)
    db.commit()

    return OrganizationOut(id=org.id, name=org.name, role=OrganizationRole.OWNER)


@router.get("/organizations")
def list_organizations(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List organizations the current user belongs to.
    """
    query = (
        db.query(OrganizationMembership)
        .join(Organization, Organization.id == OrganizationMembership.organization_id)
        .filter(OrganizationMembership.user_id == current_user.id)
    )
    total = query.count()
    memberships = query.offset(offset).limit(limit).all()

    data = [
        OrganizationOut(
            id=m.organization.id,
            name=m.organization.name,
            role=m.role,
        ).model_dump()
        for m in memberships
    ]
    return {
        "data": data,
        "meta": PaginatedMeta(limit=limit, offset=offset, count=total).model_dump(),
    }


# --- Project Management Endpoints ---

@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(
    project_in: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Create a new project inside an organization where the user is a member.
    """
    org = db.query(Organization).filter(Organization.id == project_in.organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Target Organization does not exist")

    membership = (
        db.query(OrganizationMembership)
        .filter(
            OrganizationMembership.organization_id == project_in.organization_id,
            OrganizationMembership.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this organization")

    new_project = Project(
        name=project_in.name,
        owner_id=current_user.id,
        organization_id=project_in.organization_id,
    )
    db.add(new_project)
    db.commit()
    db.refresh(new_project)
    return new_project


@router.get("/projects")
def list_projects(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Retrieve projects accessible through the authenticated user's organization memberships.
    """
    query = (
        db.query(Project)
        .join(OrganizationMembership, OrganizationMembership.organization_id == Project.organization_id)
        .filter(OrganizationMembership.user_id == current_user.id)
    )
    total = query.count()
    projects = query.offset(offset).limit(limit).all()
    return {
        "data": [ProjectOut.model_validate(p).model_dump() for p in projects],
        "meta": PaginatedMeta(limit=limit, offset=offset, count=total).model_dump(),
    }
