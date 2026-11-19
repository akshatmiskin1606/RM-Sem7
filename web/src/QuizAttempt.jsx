import React, { useEffect, useRef, useState } from 'react';

export const LETTERS = ['A', 'B', 'C', 'D'];

function AnswerReview({ questions, answers }) {
  return <section className="panel quiz-review" aria-labelledby="quiz-review-title">
    <h2 id="quiz-review-title">Answer review</h2>
    <ol className="quiz-list">
      {questions.map((question, index) => {
        const selected = answers[index];
        const correct = selected === question.answer;
        const status = correct ? 'Correct' : selected ? 'Incorrect' : 'Unanswered';
        return <li className="question" key={index}>
          <strong>{question.stem}</strong>
          <p className={`quiz-review-status ${status.toLowerCase()}`}>{status}</p>
          {selected && !correct && <p>Your answer · {selected}. {question[`option_${selected}`]}</p>}
          <p>Correct answer · {question.answer}. {question[`option_${question.answer}`]}</p>
        </li>;
      })}
    </ol>
  </section>;
}

export default function QuizAttempt({ questions, setName, onExit }) {
  const [answers, setAnswers] = useState({});
  const [submitted, setSubmitted] = useState(false);
  const heading = useRef(null);
  const total = questions.length;
  const answered = Object.keys(answers).length;
  const correct = questions.reduce((score, question, index) => score + Number(answers[index] === question.answer), 0);

  useEffect(() => {
    heading.current.focus();
  }, [submitted]);

  function retake() {
    setAnswers({});
    setSubmitted(false);
  }

  return <main className="frame workspace student-quiz" aria-labelledby="student-quiz-title">
    <div className="student-quiz-header">
      <div className="intro">
        <h1 id="student-quiz-title" ref={heading} tabIndex={-1}>{submitted ? 'Quiz results' : 'Quiz'}</h1>
        <p>{setName} · {total} {total === 1 ? 'question' : 'questions'}</p>
      </div>
      <button type="button" className="small-button quiz-back" onClick={onExit}>Back to questions</button>
    </div>
    {submitted ? <>
      <section className="panel quiz-score" aria-label="Score">
        <div>
          <p className="quiz-score-label">Score</p>
          <p className="quiz-score-value"><strong>{correct} / {total}</strong> <span>{Math.round(correct / total * 100)}%</span></p>
          <p className="quiz-score-breakdown">{answered - correct} incorrect · {total - answered} unanswered</p>
        </div>
        <button type="button" className="small-button quiz-button" onClick={retake}>Retake quiz</button>
      </section>
      <AnswerReview questions={questions} answers={answers} />
    </> : <form className="panel quiz-attempt" onSubmit={event => {
      event.preventDefault();
      setSubmitted(true);
    }}>
      <div className="quiz-progress">
        <span role="status">{answered} of {total} answered</span>
        <progress value={answered} max={total} aria-label="Quiz progress" />
      </div>
      <div className="quiz-fields">
        {questions.map((question, index) => <fieldset className="quiz-field" key={index}>
          <legend><span>{index + 1}.</span> {question.stem}</legend>
          <div className="quiz-choices">
            {LETTERS.map(letter => <label className="quiz-choice" key={letter}>
              <input type="radio" name={`question-${index}`} value={letter} checked={answers[index] === letter}
                onChange={() => setAnswers(previous => ({ ...previous, [index]: letter }))} />
              <strong>{letter}.</strong> <span>{question[`option_${letter}`]}</span>
            </label>)}
          </div>
        </fieldset>)}
      </div>
      <div className="quiz-submit">
        <span>{answered < total && 'Unanswered questions count as incorrect.'}</span>
        <button type="submit" className="small-button primary quiz-button">Submit Quiz</button>
      </div>
    </form>}
  </main>;
}
