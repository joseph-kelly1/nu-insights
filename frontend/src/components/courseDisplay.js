export const courseCode = (course) => `${course.department_code.toUpperCase()} ${course.number}`;
export const credits = (n) => `${Number(n)} ${Number(n) === 1 ? 'credit' : 'credits'}`;
