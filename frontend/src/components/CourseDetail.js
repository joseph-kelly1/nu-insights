import React from 'react';

function PrereqNode({ node }) {
  if (!node) return null;

  // Leaf node — single course
  if (node.course) {
    return (
      <span className="text-xs font-medium text-[#F3F4F6] bg-white/5 px-2.5 py-1 rounded border border-white/10">
        {node.course}
      </span>
    );
  }

  // Admission requirement
  if (node.admission_requirement) {
    return (
      <span className="text-xs italic text-gray-400">
        {node.admission_requirement}
      </span>
    );
  }

  // AND / OR group
  if (node.type && node.courses) {
    const isAnd = node.type === 'AND';

    if (isAnd) {
      return (
        <div className="space-y-2">
          {node.courses.map((child, i) => (
            <React.Fragment key={i}>
              {i > 0 && (
                <div className="flex items-center gap-2">
                  <div className="flex-1 border-t border-white/5" />
                  <span className="text-[10px] font-bold tracking-widest text-gray-500 uppercase">and</span>
                  <div className="flex-1 border-t border-white/5" />
                </div>
              )}
              <PrereqNode node={child} />
            </React.Fragment>
          ))}
        </div>
      );
    }

    // OR group — inline pills
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        {node.courses.map((child, i) => (
          <React.Fragment key={i}>
            {i > 0 && <span className="text-[10px] text-gray-500 font-medium">or</span>}
            <PrereqNode node={child} />
          </React.Fragment>
        ))}
      </div>
    );
  }

  return <span className="text-xs text-gray-400">{String(node)}</span>;
}

function CourseDetail({ course, onBack }) {
  return (
    <div className="space-y-3">
      <button
        className="text-[#FF3B30] text-xs font-medium flex items-center gap-1 hover:underline transition-colors"
        onClick={onBack}
      >
        <span className="material-symbols-outlined text-[16px]">arrow_back</span>
        Back to results
      </button>

      <div className="bg-[#28283D]/40 backdrop-blur-xl p-6 rounded-xl border border-white/5 shadow-2xl space-y-6">
        <div className="flex justify-between items-start">
          <div>
            <div className="text-[#FF3B30] font-black text-lg tracking-tight">
              {course.department_code.toUpperCase()} {course.number}
            </div>
            <h1 className="text-2xl font-bold text-[#F3F4F6] leading-tight">{course.title}</h1>
          </div>
          <div className="text-[10px] uppercase tracking-widest text-gray-400 font-bold flex-shrink-0">
            {course.credits} Credits
          </div>
        </div>

        <div className="space-y-4">
          {/* Description */}
          <div>
            <label className="text-[10px] uppercase tracking-widest text-gray-500 font-bold block mb-2">Description</label>
            <p className="text-sm text-gray-300 leading-relaxed line-clamp-3">
              {course.description || 'No description available.'}
            </p>
          </div>

          <div className="grid grid-cols-2 gap-4">
            {/* Prerequisites */}
            <div>
              <label className="text-[10px] uppercase tracking-widest text-gray-500 font-bold block mb-2">Prerequisites</label>
              {course.prerequisites && (typeof course.prerequisites === 'object') && !Array.isArray(course.prerequisites) ? (
                <div className="bg-white/[0.03] rounded-lg p-3 border border-white/5">
                  <PrereqNode node={course.prerequisites} />
                </div>
              ) : course.prerequisites && Array.isArray(course.prerequisites) && course.prerequisites.length > 0 ? (
                <div className="bg-white/[0.03] rounded-lg p-3 border border-white/5">
                  <PrereqNode node={{ type: 'AND', courses: course.prerequisites }} />
                </div>
              ) : (
                <span className="text-xs text-gray-500">None</span>
              )}
            </div>

            {/* Typical Semester */}
            {course.schedule_context && course.schedule_context.length > 0 && (
              <div>
                <label className="text-[10px] uppercase tracking-widest text-gray-500 font-bold block mb-2">Typical Semester</label>
                <div className="flex flex-wrap gap-2">
                  {[...new Set(course.schedule_context.map(e => `Year ${e.year} ${e.term}`))].map((label) => (
                    <span key={label} className="text-[10px] text-gray-400 bg-white/5 px-2 py-0.5 rounded">
                      {label}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Corequisites */}
          {course.corequisites && course.corequisites.length > 0 && (
            <div>
              <label className="text-[10px] uppercase tracking-widest text-gray-500 font-bold block mb-2">Corequisites</label>
              <div className="flex flex-wrap gap-2">
                {course.corequisites.map((coreq) => (
                  <span key={coreq} className="text-xs text-[#F3F4F6] bg-white/5 px-2 py-1 rounded">
                    {coreq}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* NUpath Attributes */}
          {course.attributes && course.attributes.length > 0 && (
            <div>
              <label className="text-[10px] uppercase tracking-widest text-gray-500 font-bold block mb-2">NUpath Attributes</label>
              <div className="flex flex-wrap gap-2">
                {course.attributes.map((attr) => (
                  <span key={attr} className="text-[10px] font-bold text-[#FF3B30] bg-[#FF3B30]/[0.12] px-3 py-1 rounded-full border border-[#FF3B30]/20">
                    {attr}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default CourseDetail;
